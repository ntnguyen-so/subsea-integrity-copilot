"""Run with ``uv run python eval\\evaluate.py``; truth remains evaluation-only."""

import json
from pathlib import Path

from subsea_copilot.evaluation import evaluate_diagnostics

if __name__ == "__main__":
    result = evaluate_diagnostics()
    destination = Path("fixtures") / "synthetic" / "evaluation-results.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, allow_nan=False))
