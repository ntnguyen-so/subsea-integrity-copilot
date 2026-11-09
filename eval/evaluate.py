"""Run ``uv run python eval\\evaluate.py`` for the offline 120-window detector cohort.

The default six scenarios x 20 held-out seeds use production diagnostics without model
calls. This entry point persists/prints measured JSON in evaluation-results.json;
recipe labels remain evaluation-only. Running it rewrites that generated evidence,
so reading a checked-in result is distinct from performing a fresh evaluation.
"""

import json
from pathlib import Path

from subsea_copilot.evaluation import evaluate_diagnostics

if __name__ == "__main__":
    result = evaluate_diagnostics()
    destination = Path("fixtures") / "synthetic" / "evaluation-results.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, allow_nan=False))
