"""Reproduce synthetic warning timing without database workers or hosted inference."""

# Inputs: number of synthetic seeds and output path. The domain evaluator owns
# detection/timing calculations; this entry point only serializes its report and
# propagates pass/fail as an exit code. Reruns overwrite the output, without services,
# database writes or hosted model calls; source-time results are not field reliability.
import argparse
import json
from pathlib import Path

from subsea_copilot.evaluation import evaluate_warning_timeliness

parser = argparse.ArgumentParser()
parser.add_argument("--seeds", type=int, default=3)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
report = evaluate_warning_timeliness(args.seeds)
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
raise SystemExit(0 if report["passed"] else 1)
