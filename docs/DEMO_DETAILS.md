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

Choose **Agent-assisted investigation**, a scenario and seed, then **Load recorded timeline**. Use **Play**, the
timeline, **Back/Forward** and **Speed** to review measurements and saved findings.
The main selector offers **5x, 10x, 20x and 30x**, defaulting to 5x.
Faster playback reuses the same saved investigations; it does not accelerate
model inference. Playback waits for each selected frame to load rather than
skipping ahead to repay loading time.

Recorded investigations are exclusive to agent-assisted mode. **Sensor alerts only**
keeps live measurement controls, anomaly/missing-value warnings and raw inspection;
it does not load recorded reports, traces, agent overlays or investigation controls.

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

The owned environment loader now enables detailed capture for this synthetic demo.
Set `$env:SUBSEA_TRACE_CONTENT = '0'` **before** dot-sourcing it to opt out.
Ordinary application defaults still require both capture and synthetic-only flags.
Restart existing API/worker processes after changing code or capture settings;
old traces are not backfilled.

To debug a **new** detailed trace, open the individual observation's Preview:

- **Tool Input:** `selection` separates application-required intake from a
  model-public `decision_summary`, or explicitly marks it `not_recorded`.
  It includes the intended check, applicable knowledge IDs and the originating
  model call/span/turn. `arguments` and `scope` show the actual requested read,
  pinned input hash, simulation window and source clock. A declared purpose is
  not proof that the call or its eventual interpretation was appropriate.
  Start with the top-level **`why_this_call`** and **`why_these_parameters`**.
  A tool's generic purpose is not its selection justification.
  For model requests, `parameter_provenance` and `declared_source_references`
  preserve the actual public parameter explanation and its stated motivating
  sources; missing explanations remain `not_recorded`, never inferred.
  Declared references are not automatically validated citations.
  For application intake, `selection.application_selection` records the rule,
  trigger and exact source/range/page/batch selection. This is application policy,
  not a fabricated model choice. No extra inference is added to narrate it.
- **Generation Input and Metadata:** Input is the actual message view;
  `model.context.input` records available tool schemas, transport instructions,
  receipt identities, context limits, and archived/consolidated receipts.
  An available receipt is not necessarily a source used in the answer.
- **Tool Output:** `execution` distinguishes accepted, executed, replayed and
  new progress. `result` contains the returned evidence or handoff, including
  original references and comparison pagination. A failed read exposes its
  diagnostic instead of a successful finding; unexpected errors are re-raised.
- **Review Output:** structural/domain validation `passed` is separate from
  semantic `accept`/`revise`. Review observations expose every verdict, reason,
  support reference and correction, plus the candidate hash. A reviewer allowing
  publication does not bypass the remaining publication gates.
- **Failures and repairs:** inspect `error.code`, the failed phase, safe exception
  type/SQLSTATE when available, structured validation feedback and the next
  repair observation. Transport repair consumes the same persisted call budget.

The explanations cover **all registered tools and roles**, including the retained
legacy policy; not only Sensor Quality:

| Read | What its selection explanation must distinguish |
| --- | --- |
| `ontology.neighbors` | Version-bound sensor/tap/gateway layout, not a pressure-history range query |
| `quality.coverage` | Expected/received/usable counts for the inherited window; absence is not zero |
| `quality.conflicts` | Conflicts and hard exclusions versus usable anomalous readings; a mandatory check does not imply a conflict exists |
| `quality.sensor_patterns` | Ranked finding IDs, concern priorities, offset/page size and histories not read by this page |
| `pressure.measurements` | Actual pinned network measurements before choosing a cause; no screening hypothesis supplied as a diagnosis |
| `evidence.get` | Explicit sources, source tasks or quality-claim/read links, batch boundaries, and archived-receipt retrieval when model-requested |
| `task.result` | Compatible specialist identity and precise comparison delivery: one-page current policy, all cited comparisons in legacy reviewed context, or result-only protocols |
| `history.search` | Concrete operating/calibration counter-question, chosen query/assets and incident-time validity |
| `history.read` | Actual preceding search hits, original bodies including contradictions, source search-call IDs and bounded document groups |
| `history.compare` | Chosen sensor group, actual historical start/split/end, paired-only choice and why these differ from the monitoring window |
| `event.assess` / `event.counterevidence` | Legacy screening prerequisites and opposing evidence, not physical confirmation |
| `location.fit` | Legacy eligibility gate and fit limitations, not an exact proven leak point |
| `criteria.explain` | Legacy publication/decision limits, not permission to override an unresolved cause |

For example, at a pinned monitoring window `[60,120)` and source clock `125s`,
the tool must not describe a history comparison as necessarily using the same
60 seconds. Initial comparisons have their own bounded lookback and midpoint
split; model-requested comparisons must explain their actual chosen boundaries.
Likewise, two initial `evidence.get` calls may be disjoint groups of 24 and 2
sources referenced by completed quality reads. **24 is the application's upfront
batch size**, not the gateway's maximum ID allowance or a diagnostic threshold.
The trace links each selected source back to the returned claim and source call.

Open each **handoff Input** for `why_this_handoff` and `why_this_scope`.
The validated plan and application prerequisite order are distinct from a free
model choice; constrained plans must not be narrated as independent model insight.
Older traces are not rewritten when these explanations are added.

#### Why does an agent read tools, submit an answer, then run a guardrail?

The tree is an execution sequence, not a list of autonomous model decisions.
Open the **parent agent Input** for `execution_procedure`: the role's job,
mandatory read names, who executes them, allowed next steps and validation limits.
Its **Metadata > `workflow.intake.input`** lists the actual upfront calls and
their IDs. A resumed conversation explicitly identifies checkpoint reuse instead
of inventing a fresh intake sequence.

For S7 +120s, Sensor Quality's four required names are `ontology.neighbors`,
`quality.conflicts`, `quality.coverage` and `quality.sensor_patterns`.
The returned quality claims reference 26 sources, so application code adds two
`evidence.get` batches of 24 and 2. That makes **six calls to five distinct tools**,
all before the first model turn. Six is not a quota, an anomaly threshold or
evidence that the model decided six reads were sufficient. The health page is
bounded; unreviewed instruments are not declared healthy.

The subsequent **Generation Output > `workflow_transition`** exposes the actual
runtime preference, final-only constraint, outstanding mandatory reads and number
of model tool requests. No tool requests means the graph tries to parse and
validate the submitted candidate. **Submit answer is not another tool call or an
accepted answer.** The model's unreported reason for stopping remains
`not_recorded`; do not infer confidence from this route.

The **answer-check Output** explains `why_this_check`, `execution_authority`,
the validator entry point, its contract, pass/failure routing and limits.
This guardrail executes Python validation, not another model call. It checks the
structured result and applicable scope, receipt, source and role requirements.
It does not independently establish that specialist prose is correct or that a
physical fault exists. The engineer-v2 coordinator has a separate semantic
review before publishing its report. Finally, the **agent Output >
`execution_summary`** explains completion and the next recipient.

Captured fields are redacted and capped at **524,288 characters per field**.
Oversized captures remain valid JSON with an explicit `capture.truncated` flag,
a redacted-content fingerprint and a partial `preview`; they are not full
transcripts. Provider-private reasoning and credentials are excluded, and the
local telemetry audit remains content-free.

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
# Start all three independent suites together (eight network workers).
uv run --no-sync subsea spatial-evaluation --suite all --split held_out `
  --seed 20261110 --output eval\results\spatial-all-new
```

`--suite all` starts every suite without a shared worker cap and publishes
finished suites through one writer. Each network advances in order and holds
source time through investigation and admission: queued future checkpoints are
not idle workers. Independent model calls share a warm SDK runtime; only
session-file cleanup is serialized, without serializing inference.

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
Every selected case starts concurrently; its reviewer waits for its own answer.

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
