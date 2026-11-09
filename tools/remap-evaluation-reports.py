"""Re-extract archived Evaluation reports from incident text and rescore; no agents rerun."""

import argparse

from subsea_copilot.config import Settings
from subsea_copilot.contracts import utc_now
from subsea_copilot.evaluation_mapping import run_mapping
from subsea_copilot.llm.copilot_cli import CopilotCLIChatModel
from subsea_copilot.reference_evaluation import PUBLIC_REPORT, read_evaluation, write_report
from subsea_copilot.spatial_evaluation import spatial_metrics
from subsea_copilot.telemetry import Telemetry
from subsea_copilot.temporal_evaluation import agent_process_metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    original = read_evaluation()
    archive = PUBLIC_REPORT.with_name("evaluation-before-incident-only.json")
    if not archive.exists():
        write_report(archive, original)
    report = read_evaluation()
    telemetry = Telemetry(runtime_dir=settings.runtime_dir)
    failures = 0
    try:
        model = CopilotCLIChatModel(runtime_dir=settings.runtime_dir, model_id="gpt-6.1-sol")
        for cohort in [report, *report.get("additional_evaluations", [])]:
            networks = {network["id"]: network for network in cohort.get("networks", [])}
            for case in cohort.get("cases", []):
                if not case.get("accepted_report"):
                    continue
                if (case.get("extraction") or {}).get("source_text_scope") == (
                    "incident-answer-only-v1"
                ):
                    if case["extraction"]["status"] == "completed":
                        continue
                    if not args.retry_failed:
                        failures += 1
                        continue
                    case.setdefault("previous_extractions", []).append(case["extraction"])
                network = networks[case["network_id"]]
                catalog = [{
                    "id": sensor["id"], "station_id": sensor["station_id"],
                    "segment_id": sensor["segment_id"],
                } for sensor in network["pack"]["sensors"]]
                case["extraction"] = run_mapping(
                    model, case["interpretation"], catalog, telemetry,
                    tenant_id=cohort.get("tenant_id", "archived-evaluation"),
                    generation_id=case.get("generation_id", case["root_id"]),
                )
                failures += case["extraction"]["status"] != "completed"
                print(f"{case['case_id']}: {case['extraction']['status']}", flush=True)
            cohort["extraction_source"] = "Visible incident report only; no detector diagnoses"
            cohort["remapped_at"] = utc_now().isoformat()
            cohort["metrics"] = spatial_metrics(cohort)
            cohort["agent_process"] = agent_process_metrics(cohort)
        if read_evaluation() != original:
            raise RuntimeError("Evaluation changed concurrently; refusing to overwrite it")
        write_report(PUBLIC_REPORT, report)
        if failures:
            raise RuntimeError(f"{failures} failed extractions preserved; no labels inferred")
        print("Evaluation maps and scores now use incident-report-only labels.", flush=True)
    finally:
        telemetry.close()


if __name__ == "__main__":
    main()
