"""Export scoped synthetic cohort receipts, never model reasoning or credentials."""

import argparse
import json
from pathlib import Path

from subsea_copilot.config import Settings
from subsea_copilot.qualification import PRIMARY_QUESTIONS, model_receipts
from subsea_copilot.store import Store


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    cohort = report["agents"]
    tenant = cohort["qualification_tenant_id"]
    if not isinstance(tenant, str) or not tenant.startswith("qualification-"):
        raise ValueError("Only a declared synthetic qualification tenant may be exported")
    settings = Settings.from_env()
    with Store(
        settings.database_dsn, tenant_id=tenant, site_id=settings.site_id,
        tools_dsn=settings.tools_dsn,
    ) as store:
        for row in cohort["results"]:
            root = store.get_task(row["root_id"])
            if root.question not in PRIMARY_QUESTIONS:
                raise ValueError("Receipt contains a question outside the frozen synthetic cohort")
            tasks = [task for task in store.list_tasks(root.generation_id)
                     if task.root_id == root.id]
            row["answer"] = root.answer
            row["model_receipts"] = model_receipts(store, [task.id for task in tasks])
            row["task_summary"] = [
                {"task_id": task.id, "role": task.role, "state": task.state,
                 "model_calls": task.model_calls, "tool_calls": task.tool_calls,
                 "error_code": task.error_code}
                for task in tasks
            ]
    metadata = [
        receipt for row in cohort["results"] for receipt in row["model_receipts"]
    ]
    cohort["observed_models"] = sorted({
        receipt["observed_model"] for receipt in metadata
        if isinstance(receipt["observed_model"], str)
    })
    cohort["observed_cli_versions"] = sorted({
        receipt["cli_version"] for receipt in metadata
        if isinstance(receipt["cli_version"], str)
    })
    cohort["live_model_evidence"] = cohort["mode"] == "live" and bool(cohort["observed_models"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print("Scoped synthetic answers and model metadata exported; no reasoning/content traces.")


if __name__ == "__main__":
    main()
