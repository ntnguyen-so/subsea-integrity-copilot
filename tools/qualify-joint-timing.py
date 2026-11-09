"""Held-out joint-timing probe: execution gates, with semantic review still required."""

# Two fresh hosted S7 arms preserve per-instrument before/after distributions while
# changing only P7 temporal order. Requires database/checkpointer and hosted Copilot.
# Creates a new tenant and timestamped runtime report; reruns repeat real calls rather
# than reuse prior inference. Equal marginal hashes check the controlled manipulation,
# not equal multivariate evidence or independently established causal correctness.
import hashlib
import json
import math
import time
from datetime import timedelta
from pathlib import Path
from statistics import median
from uuid import uuid4

from subsea_copilot.budgets import ROOT_WATCHDOG_SECONDS
from subsea_copilot.casefile import build_casefile
from subsea_copilot.config import Settings
from subsea_copilot.contracts import RawRecord, ReplaySession, utc_now
from subsea_copilot.diagnostics import analyze_window
from subsea_copilot.ingest import normalize_records
from subsea_copilot.llm.copilot_cli import CopilotCLIChatModel
from subsea_copilot.runtime.checkpointer import postgres_checkpointer
from subsea_copilot.runtime.gateway import ToolGateway
from subsea_copilot.runtime.workflow import AgentService
from subsea_copilot.store import Store
from subsea_copilot.synthetic import SOURCE_VERSION, generate_scenario
from subsea_copilot.telemetry import Telemetry


def main():
    settings = Settings.from_env()
    tenant = "joint-timing-" + uuid4().hex[:12]
    source = generate_scenario("S7", 91002, site_id=settings.site_id)
    baseline = normalize_records(source.baseline, source.pack)
    rows = [
        row
        for row in normalize_records(source.records, source.pack)
        if row.received_at <= source.epoch + timedelta(seconds=115)
    ]
    instruments = [f"P7-ST{station}-{side}" for station in range(1, 5) for side in "AB"]
    centers = {
        identifier: median(
            row.value
            for row in baseline
            if row.sensor_id == identifier and row.validity == "usable" and row.value is not None
        )
        for identifier in instruments
    }
    arms = []
    telemetry = Telemetry(runtime_dir=settings.runtime_dir)
    try:
        with (
            Store(
                settings.database_dsn,
                tenant,
                settings.site_id,
                settings.tools_dsn,
                qualification=True,
            ) as store,
            postgres_checkpointer(settings.checkpoint_dsn) as saver,
        ):
            for staggered in (False, True):
                samples = [
                    row
                    for row in rows
                    if row.sensor_id not in instruments
                    or not 50 <= (row.observed_at - source.epoch).total_seconds() < 110
                ]
                values = {identifier: {"before": [], "after": []} for identifier in instruments}
                probe_records = []
                for identifier in instruments:
                    for second in range(50, 110):
                        original_second = second
                        # Rotate the later group's 40s post-period by 20s: magnitudes
                        # stay identical as sets, but cross-instrument alignment changes.
                        if staggered and instruments.index(identifier) >= 4 and second >= 70:
                            original_second = 70 + (second - 70 + 20) % 40
                        pressure = (
                            centers[identifier]
                            + 0.005 * math.sin(original_second)
                            - (0.55 if 70 <= original_second < 90 else 0)
                        )
                        values[identifier]["before" if second < 70 else "after"].append(pressure)
                        timestamp = (source.epoch + timedelta(seconds=second)).isoformat()
                        probe_records.append(
                            RawRecord(
                                sensor_id=identifier,
                                channel="pressure",
                                observed_at=timestamp,
                                received_at=timestamp,
                                value=pressure,
                                unit="bar",
                                source_id="controlled-timing-probe",
                                source_record_id=f"{identifier}-{second}",
                            )
                        )
                samples.extend(normalize_records(probe_records, source.pack))
                if any(len(v["before"]) != 20 or len(v["after"]) != 40 for v in values.values()):
                    raise ValueError("Probe observation support changed.")
                marginal_hash = hashlib.sha256(
                    json.dumps(
                        {
                            identifier: {period: sorted(v) for period, v in periods.items()}
                            for identifier, periods in values.items()
                        },
                        sort_keys=True,
                    ).encode()
                ).hexdigest()
                replay = store.create_replay(
                    ReplaySession(
                        id="joint-" + uuid4().hex,
                        tenant_id=tenant,
                        site_id=settings.site_id,
                        scenario="S7",
                        source_version=SOURCE_VERSION,
                        mode="live",
                        clock_seconds=115,
                        epoch=source.epoch,
                    )
                )
                store.save_observations(replay.id, samples)
                snapshot = store.save_window(
                    analyze_window(
                        source.pack,
                        baseline,
                        samples,
                        replay.id,
                        110,
                        115,
                        source.epoch,
                        tenant_id=tenant,
                    )
                )
                service = AgentService(
                    store,
                    lambda _role, _mode: CopilotCLIChatModel(
                        runtime_dir=settings.runtime_dir, model_id="gpt-6.1-sol"
                    ),
                    saver,
                    telemetry,
                )
                started = time.monotonic()
                root = service.submit_question(
                    replay,
                    snapshot,
                    "Investigate P7-ST1-A/B through P7-ST4-A/B jointly over source "
                    "+50 to +110 seconds, split at +70. Do these eight instruments "
                    "support one shared pressure transition or competing explanations? "
                    "Inspect temporal profiles, dependence and counterevidence, "
                    "not only individual magnitudes. Keep other regional warnings separate.",
                    idempotency_key="frozen-joint-timing",
                )
                while root.state not in {"SUCCEEDED", "ABSTAINED", "FAILED", "CANCELLED"}:
                    if time.monotonic() - started > ROOT_WATCHDOG_SECONDS:
                        raise RuntimeError("Probe exceeded the bounded workflow deadline.")
                    if not service.run_once():
                        time.sleep(0.05)
                    root = store.get_task(root.id)
                casefile = None
                if root.state in {"SUCCEEDED", "ABSTAINED"}:
                    dependencies = ToolGateway(store, root, snapshot, telemetry).dependencies()
                    receipts = [
                        {"task_id": dependency.id, **receipt}
                        for dependency in dependencies
                        for receipt in store.tool_receipts(dependency.id)
                        if str(receipt["name"]).startswith("history.")
                    ]
                    casefile = build_casefile(root, snapshot, dependencies, receipts)
                tasks = store.list_tasks(replay.id)
                arms.append(
                    {
                        "staggered": staggered,
                        "marginal_hash": marginal_hash,
                        "input_hash": snapshot.input_hash,
                        "numerical_hypothesis": snapshot.event.hypothesis,
                        "root": root.model_dump(mode="json"),
                        "casefile": casefile.model_dump(mode="json") if casefile else None,
                        "elapsed_seconds": time.monotonic() - started,
                        "model_calls": sum(task.model_calls for task in tasks),
                        "tool_calls": sum(task.tool_calls for task in tasks),
                    }
                )
        report = {
            "matching_individual_before_after_distributions": arms[0]["marginal_hash"]
            == arms[1]["marginal_hash"],
            "arms": arms,
            "inference_retries": 0,
            "limitations": [
                "Two synthetic held-out timing probes, not a population accuracy estimate.",
                "Only the controlled P7 within-period temporal order changes.",
                "The eight P7 streams are complete authored probe fixtures, not gap imputation.",
                "The full network and common gateway dependence remain visible.",
                "Accepted contracts do not grade causal correctness; independent review required.",
                "No waveform propagation, hydraulic validation or human time-saving claim.",
            ],
        }
        output = Path("runtime") / f"joint-timing-live-{utc_now():%Y%m%dT%H%M%SZ}.json"
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        # This exit status qualifies controlled inputs and execution, not the
        # semantic correctness of the two model-written engineering conclusions.
        qualified = report["matching_individual_before_after_distributions"] and all(
            arm["root"]["state"] in {"SUCCEEDED", "ABSTAINED"} for arm in arms
        )
        print(
            json.dumps(
                {
                    "artifact": str(output),
                    "execution_qualified": qualified,
                    "states": [arm["root"]["state"] for arm in arms],
                }
            )
        )
        if not qualified:
            raise SystemExit(1)
    finally:
        telemetry.close()


if __name__ == "__main__":
    main()
