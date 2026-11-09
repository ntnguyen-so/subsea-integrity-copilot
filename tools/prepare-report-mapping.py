"""Preserve Evaluation-compatible labels for an already accepted synthetic report."""

# Select a stored task (DB access required) or successful playback-library entries.
# This DOES require authenticated hosted Copilot when extraction is needed: it maps
# accepted report text to quoted presentation labels, not a fresh incident diagnosis.
# Saves runtime mapping receipts via prepare_report_mapping; existing outcomes are
# reused unless an explicit failed retry is requested. No accepted answer is rewritten.
import argparse

from subsea_copilot.config import Settings
from subsea_copilot.llm.copilot_cli import CopilotCLIChatModel
from subsea_copilot.playback import load_library
from subsea_copilot.report_mapping import prepare_report_mapping
from subsea_copilot.store import Store
from subsea_copilot.synthetic import generate_pack
from subsea_copilot.telemetry import Telemetry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--task-id")
    selection.add_argument("--library", action="store_true")
    parser.add_argument("--tenant", default="demo")
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    telemetry = Telemetry(runtime_dir=settings.runtime_dir)
    try:
        if args.library:
            rows = [(row.task, row.pack) for row in load_library(
                settings.runtime_dir / "agent-playback.json",
            ).recordings if row.task.state == "SUCCEEDED"]
        else:
            with Store(settings.database_dsn, args.tenant, settings.site_id,
                       settings.tools_dsn, qualification=args.tenant != "demo") as store:
                task = store.get_task(args.task_id)
                snapshot = store.get_window(task.snapshot_id)
                rows = [(task, generate_pack(snapshot.site_id, version=snapshot.pack_version))]
        # Geometry/catalog constrain identifiers; the mapper must quote the report,
        # not invent sensor faults from detector flags or a numerical location.
        for task, pack in rows:
            receipt = prepare_report_mapping(
                settings.runtime_dir, task, pack,
                CopilotCLIChatModel(runtime_dir=settings.runtime_dir, model_id="gpt-6.1-sol"),
                telemetry,
                retry_failed=args.retry_failed,
            )
            if receipt["status"] != "completed":
                raise RuntimeError(f"Extraction failed: {receipt.get('error_code')}")
            issues = receipt["mapping"]["sensor_issues"]
            print(f"Preserved {len(issues)} quoted instrument labels for {task.id}")
            for issue in issues:
                print(f"{issue['sensor_id']}: {issue['kind']} ({issue['assertion']})")
    finally:
        telemetry.close()


if __name__ == "__main__":
    main()
