"""Seed a mature fictional fixture in the console tenant without automatic inference."""

# Requires configured database credentials/services. Each run creates a fresh live-
# labeled replay plus arrival-gated observations and one mature snapshot, then prints
# their IDs. Mode "live" here is metadata, not evidence that inference has occurred.
# Existing rows are preserved; reruns accumulate fixtures rather than reset the tenant.
import argparse
import json
from datetime import datetime, timedelta
from uuid import uuid4

from subsea_copilot.config import Settings
from subsea_copilot.contracts import ReplaySession
from subsea_copilot.diagnostics import analyze_window
from subsea_copilot.ingest import normalize_records
from subsea_copilot.store import Store
from subsea_copilot.synthetic import SOURCE_VERSION, generate_scenario


def main() -> None:
    settings = Settings.from_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=["S1", "S4"], default="S4")
    args = parser.parse_args()
    source = generate_scenario(args.scenario, site_id=settings.site_id)
    with Store(
        settings.database_dsn,
        tenant_id=settings.tenant_id,
        site_id=settings.site_id,
        tools_dsn=settings.tools_dsn,
    ) as store:
        replay = store.create_replay(
            ReplaySession(
                id="handoff-" + uuid4().hex,
                tenant_id=store.tenant_id,
                site_id=settings.site_id,
                scenario=args.scenario,
                source_version=SOURCE_VERSION,
                mode="live",
                epoch=source.epoch,
            )
        )
        # Reconstruct only records received by +185s for the +180s window; observed
        # timestamps alone would leak late/future evidence into this handoff fixture.
        observations = normalize_records(
            [
                row
                for row in source.records
                if datetime.fromisoformat(row.received_at.replace("Z", "+00:00"))
                <= source.epoch + timedelta(seconds=185)
            ],
            source.pack,
        )
        store.save_observations(replay.id, observations)
        snapshot = store.save_window(
            analyze_window(
                source.pack,
                normalize_records(source.baseline, source.pack),
                observations,
                replay.id,
                180,
                185,
                source.epoch,
                tenant_id=store.tenant_id,
            )
        )
        store.save_replay(
            replay.model_copy(
                update={
                    "clock_seconds": 185,
                    "latest_window_id": snapshot.id,
                    "last_endpoint": 180,
                }
            ),
            expected_version=replay.version,
        )
        print(json.dumps({"id": replay.id, "snapshot_id": snapshot.id, "mode": "live"}))


if __name__ == "__main__":
    main()
