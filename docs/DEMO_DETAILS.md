# Demo and evaluation reference

Start with the [README](../README.md) for installation and login. This guide
contains operating commands, not a development changelog. For design and code
navigation, see the [engineering report](REPORT.md); for measured outcomes and
retained failures, see [qualification results](RESULTS.md).

**Synthetic data only. Read-only decision support, not a safety system.**
Run commands from the repository root in PowerShell with the owned environment
loaded. Live investigations and report mapping use hosted inference and consume
your Copilot allowance; playback and document export do not.

## Choose a walkthrough

| Path | Requirements | What it demonstrates |
|---|---|---|
| **Evaluation → Detection** | Console and database | Bundled synthetic evaluation, original reports and truth-versus-agent maps. Playback makes no model calls. |
| **Live → Sensor alerts only** | Console and database | Measurements, data quality and anomaly alerts without inference. |
| **Load recorded timeline** | A locally prepared recording library | Saved investigations at their original evidence times, with retained supported, abstained and failed outcomes. |
| **Agent-assisted investigation** | Authenticated Copilot CLI and database/checkpoints | Fresh, bounded specialist investigation and grounding review. Allow several minutes; acceptance is not guaranteed. |

Use the **same scenario, seed and measurement window** when comparing workflows.
S1-S6 have 24 instruments on three segments; S7 has 112 on seven segments.
S7 is the customer brief's selected example; S1 is the smaller code walkthrough.
Neither is a hydraulic or field-accuracy validation.

Monitoring warnings do not wait for models. Agent reports apply only to their
pinned windows; a missing report is not a healthy-pipeline verdict. The dashboard
has no general chat/question-entry interface.

## Dashboard recorded walkthrough

Choose a scenario and seed, then **Load recorded timeline**. Use **Play**, the
timeline, **Back/Forward** and **Speed** to review measurements and saved findings.
The main selector offers **5x, 10x, 20x and 30x**, defaulting to 5x.
Faster playback reuses the same saved investigations; it does not accelerate
model inference. Playback waits for each selected frame to load rather than
skipping ahead to repay loading time.

The measurement map follows the selected source time. An agent overlay on that
map requires matching evidence; the report retains its explicitly labelled
investigation time. Findings are never backfilled onto earlier windows.
Open a sensor to compare actual readings and report quotations. **Review evidence**
and execution details expose sources, grounding decisions, usage and original
trace links, not private model reasoning.

Switching to **Live investigation** makes no model call by itself. Explicitly
selecting **Run agents at +Xs** creates a fresh investigation in a separate replay
at the chosen endpoint. It does not rewrite or cancel the saved recording.
**Start new run** instead starts ordinary live monitoring.

### Prepare a local recording library

This is optional and makes real hosted calls. A clean clone contains the bundled
Detection evaluation, not the locally generated main-timeline library.
Use a **new output directory** on each recording run. First start the optional
trace services described under [observability](#live-runtime-and-observability);
recording verification requires them.

```powershell
. .\tools\load-environment.ps1
$env:SUBSEA_TELEMETRY_ENABLED = '1'
$env:SUBSEA_TRACE_CONTENT = '1'
$env:SUBSEA_SYNTHETIC_ONLY = '1'
uv run --no-sync subsea provider-check --mode live --model gpt-6.1-sol
uv run --no-sync python tools\verify-s7-agents.py `
  --scenarios S1 S2 S3 S4 S5 S6 S7 --record `
  --checkpoints 95 100 105 110 120 135 150 180 360 `
  --workers 4 --output runtime\recordings-new
uv run --no-sync python tools\prepare-agent-playback.py --runs runtime\recordings-new
```

`--record` requires validated terminal reports, final grounding acceptance and
verified stored traces. Supported reports also need completed report-to-map
extraction. A reviewed abstention is a valid recording, not a supported physical
diagnosis or leak clearance. Raw manifests and failed attempts remain available.
`--workers` controls checkpoint concurrency, not parallel reasoning inside a root.

Export merges by task ID into `agent-playback.json` in the configured runtime
directory. It reads original database records and makes **no inference calls**.
The library, mappings and trace services must be retained for local playback.
Published recording receipts and their limitations are in [RESULTS.md](RESULTS.md).

To refresh an older library's original trace metadata, stop the dashboard first:

```powershell
uv run --no-sync python tools\prepare-agent-playback.py --refresh-traces
```

This changes trace metadata only; missing original metadata is an error, not
permission to substitute a different execution.

### Prepare missing report mappings

Normal live investigations save their own report-to-map extraction. Preparing
older recordings is a separate **hosted** operation:

```powershell
uv run --no-sync python tools\prepare-report-mapping.py --library
```

Use `--retry-failed` only for an explicit retry of preserved failed extractions.
The mapper quotes the accepted report; it does not rerun or rewrite diagnosis.
Mapping failure remains visible without erasing the report.

## Live runtime and observability

The default transport reuses one owned, installed Copilot CLI runtime through the
pinned Python SDK. Each model call creates and deletes an isolated, native-tool-
disabled session. Application tools remain scoped and audited. Authentication,
quota, timeout or grounding failures are explicit; no recording or alternate
transport is silently substituted.

For explicit transport troubleshooting, set
`$env:SUBSEA_COPILOT_TRANSPORT = 'cli'` before server startup. This selects the
older per-call subprocess adapter; there is no automatic transport fallback.

Jaeger and Langfuse are optional for ordinary monitoring. To inspect stored traces:

```powershell
. .\tools\load-environment.ps1
docker compose up -d --wait
docker compose -f docker-compose.langfuse.yml up -d --wait
$env:SUBSEA_TELEMETRY_ENABLED = '1'
$env:SUBSEA_TRACE_CONTENT = '1'
$env:SUBSEA_SYNTHETIC_ONLY = '1'
uv run --no-sync subsea serve
```

Only enable content capture for the explicitly synthetic data. Export success
does not prove a trace is stored: use the task's original trace link/verification.
The console shows reported usage and a labelled API-equivalent cost estimate,
**not a Copilot bill**; missing telemetry is unknown, not zero.

When a server holds Python executables open on Windows, use `--no-sync` for
auxiliary commands. Install/restore dependencies before starting the server.

## Reproduce evaluation

Use new output paths and retain every first attempt and explicit retry.
Historical results belong to their recorded policy, prompts, model and input
hashes; they do not automatically qualify current code.

### Detection and spatial findings

```powershell
. .\tools\load-environment.ps1
$env:SUBSEA_TRACE_CONTENT = '1'
$env:SUBSEA_SYNTHETIC_ONLY = '1'
uv run --no-sync subsea spatial-evaluation --split development `
  --seed 20261109 --output eval\results\spatial-development-new
# Freeze code/prompts before the separate held-out measurement run.
uv run --no-sync subsea spatial-evaluation --split held_out `
  --seed 20261110 --output eval\results\spatial-held-out-new
```

This makes fresh hosted investigations and truth-blind report-mapping calls.
Independent synthetic labels, missed findings, failures and withheld intervals
remain in deterministic scoring denominators. A `held_out` label is not an
independently authored customer trial. See the report for metric boundaries.

### Agent answer quality

```powershell
uv run --no-sync subsea agent-evaluation --split all `
  --output runtime\agent-evaluation-new
```

The eight authored factual-reference cases are in
[`agent-reliability-cases.json`](../fixtures/synthetic/agent-reliability-cases.json).
Factual checks and the six advisory model-review dimensions are separate.
Judge opinions do not establish expert agreement or field reliability.

### Historical comparators and specialist checks

For the matched fixed-versus-agent protocol and commands, use
[AGENT_EVALUATION.md](AGENT_EVALUATION.md). Additional CLI paths are available
through `uv run --no-sync subsea --help`: `reference-evaluation`, `golden`,
`evaluate` and `agent-audit`. These have distinct scopes; do not merge their
scores or mistake scripted contract checks for hosted trials.

## Development checks

Offline checks do not need a model or database:

```powershell
uv run --no-sync pytest -m "not integration and not live" --disable-socket -q
uv run --no-sync ruff check .
uv run --no-sync mypy src
npm run typecheck
npm run build
```

Integration fixtures reapply the owned database schema. **Stop the monitoring
server and finish qualification runs first**; do not run migrations or competing
integration-test processes against active workers.

```powershell
. .\tools\load-environment.ps1
uv run --no-sync pytest -m integration -q
```

Browser tests need the console and installed Chrome; start the server again first:

```powershell
npx playwright test console.spec.ts investigation-playback.spec.ts --reporter=line
```

Specs explicitly opt in to hosted checks; read their prerequisites before enabling
them. Windows Application Control has blocked the installed compiled `mypy` in
prior runs; an approved environment is required before claiming a Python typecheck
pass. Check outcomes for the actual checkout rather than copying old pass counts.

## Interview materials

Use [ONE_PAGE_BRIEF.pdf](ONE_PAGE_BRIEF.pdf) as the single customer/submission
brief; its editable source is [ONE_PAGE_BRIEF.md](ONE_PAGE_BRIEF.md).
Open [INTERVIEW_DECK.html](INTERVIEW_DECK.html) in Chrome/Edge with `assets/`
alongside it. [INTERVIEW_DECK.pdf](INTERVIEW_DECK.pdf) is the print export.
The deck covers the full meeting; the README links the 30-minute technical route.

Rebuild locally without inference:

```powershell
$env:UV_NO_SYNC = '1'  # Dependencies are already installed; leave running services alone.
node scripts\render-brief.cjs
npm run deck:pdf
npm run deck:test
```

Rehearse recorded results for predictable timing. Any optional fresh investigation
must be labelled live, and a failure must never be disguised as playback.
