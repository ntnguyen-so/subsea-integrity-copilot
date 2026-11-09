"""Shared execution allowances; evidence and authority checks are independent.

These are demo resource/latency ceilings, not calibrated engineering thresholds
or confidence levels. The registry derives per-role call budgets from the same
multiplier; store reservations persist spend across retries and worker restarts.
Larger allowances never expand tool scope or weaken result validation.
"""

# Central scale factor: time/call/page allowances expand together, cooldown shrinks.
BUDGET_MULTIPLIER = 3
# Effective bounds: root 900s, watchdog 990s, model call 180s, task lease 1080s.
# The watchdog/lease outlast the root; a child inherits the root's original deadline.
ROOT_DEADLINE_SECONDS = 300 * BUDGET_MULTIPLIER
ROOT_WATCHDOG_SECONDS = 330 * BUDGET_MULTIPLIER
WORKER_POLL_LIMIT = 100 * BUDGET_MULTIPLIER
AUTOMATIC_COOLDOWN_SECONDS = 60 // BUDGET_MULTIPLIER
MODEL_TIMEOUT_SECONDS = 60 * BUDGET_MULTIPLIER
TASK_LEASE_SECONDS = 360 * BUDGET_MULTIPLIER
SCHEMA_REPAIR_LIMIT = BUDGET_MULTIPLIER
# Three author revisions allow four critic reviews, still within task call ceilings.
REFLECTION_LIMIT = BUDGET_MULTIPLIER
FRESH_REFLECTION_LIMIT = 3
REVIEW_ROUND_LIMIT = REFLECTION_LIMIT + 1
GRAPH_RECURSION_LIMIT = 50 * BUDGET_MULTIPLIER
# Independent byte/character caps bound delivery; page sizes are not exhaustive-review promises.
TOOL_RESULT_MAX_BYTES = 16 * 1024 * BUDGET_MULTIPLIER
HISTORY_CONTEXT_MAX_CHARS = 21 * 1024 * BUDGET_MULTIPLIER
HISTORY_DOCUMENT_LIMIT = 3 * BUDGET_MULTIPLIER
COMPARISON_SENSOR_LIMIT = 8 * BUDGET_MULTIPLIER
HISTORY_RANGE_SECONDS = 300 * BUDGET_MULTIPLIER
HEALTH_PAGE_SIZE = 8 * BUDGET_MULTIPLIER
CONTEXT_SENSOR_LIMIT = 24 * BUDGET_MULTIPLIER
