# Subsea Integrity Copilot

Read-only FDE demo for a fictional offshore gas operator. Existing anomaly
detectors flag pressure readings; agents help engineers investigate those alerts,
distinguish sensor faults from possible leaks, and recommend a supported inspection
interval or abstain. **Synthetic data only; not a safety system.**

The product hypothesis is reusable expert knowledge: reviewed procedures and
worked evidence help less-experienced engineers investigate at scale. Knowledge
elicitation/approval and onboarding benefit still require customer validation.
Assume ten minutes for manual analysis; allow up to **five minutes for a grounded
LLM report**, prioritizing correctness. These are planning assumptions, not
measured labor savings.

The global **monitoring warning** is numerical and never waits for the LLM.
It follows the latest window even when a historical investigation is pinned.
Source loss is a coverage warning, not a no-leak conclusion. A disconnected
browser labels the retained assessment as stale.

Private repository: https://github.com/ntnguyen-so/subsea-integrity-copilot.
Reviewers need repository access before the interview.

## Run on Windows

Requires Python 3.11, `uv`, Node.js, Docker Desktop with Linux containers, and
PowerShell. Live mode additionally requires an authenticated GitHub Copilot CLI
with model access. Scripted mode works without inference but is visibly labeled;
it is not evidence of live-model performance.

```powershell
uv sync --locked
npm ci
npm run build
.\tools\bootstrap.ps1
. .\tools\load-environment.ps1
docker compose up -d --wait
docker compose -f docker-compose.langfuse.yml up -d --wait
uv run subsea migrate
uv run subsea serve
```

Bootstrap runs **once** and refuses overwriting credentials. It stores user-only
credentials outside the repository at `%LOCALAPPDATA%\SubseaCopilot\secrets.json`.
Dot-source the loader in every new terminal before running database commands.

Open http://127.0.0.1:8086; username `operator`, password from the locally loaded
`SUBSEA_OPERATOR_PASSWORD`. Never commit or share credential values. Langfuse is
http://127.0.0.1:3001 (`operator@subsea.local`, `LF_ADMIN_PASSWORD`); optional Jaeger
is http://127.0.0.1:16687. Services/volumes are project-owned and loopback-bound.
Stopping Compose without `-v` preserves evidence.

### Five-minute operator walkthrough

The default view has three areas: **pipeline map, sensor trend and agent
assessment**. Source time and the current warning stay visible. Run settings,
engineer questions, detection criteria and system diagnostics expand only when
needed. Comparisons appear after selecting them; full reports open in Agents,
not as a second answer beneath the live dashboard.

The light theme uses matching map and chart meanings: **amber** marks individual
pressure anomalies, a **red cross** marks a quality concern, a **blue ring**
selects the graphed instrument, and grey-filled markers are **not assessed**.
Dashed sensor outlines show missing/excluded readings; amber diamonds show
correlated-drop support. These flags can coexist and are not confirmed leak or
hardware-failure diagnoses. Chart keys separately identify pressure, baseline
thresholds and missing-data bands; map, table and trend retain the same window.

1. Choose **S1**, open **Run settings** and select **COPILOT HOSTED** for a genuine LLM demonstration
   (**SCRIPTED** is explicitly an offline contract example). Create a generation,
   select 10x speed and Play. The continuously updated UTC clock comes from the
   server, never browser-extrapolated measurements. Samples arrive every simulated
   second; 60s windows slide every 5s after the 5s lateness allowance.
2. Select a station on the map or an instrument in the alarm list. Its pressure
   trend continues following received windows. Inspect threshold crossings, gaps
   and paired instruments just as in a manual investigation. Check up to four
   instruments for a custom same-window comparison. During fast replay or slow
   reads, the map, alarm list and trend advance together only after scoped
   observations arrive; the last complete view stays visible instead of flashing
   blank or mixing windows. The latest numerical warning remains independent.
3. Qualifying leak, instrumentation and coverage-loss warnings automatically queue
   the specialists. A first **unresolved-only** pattern instead shows explicit
   evidence triage for at most one source window; a qualifying warning bypasses
   that hold immediately. Persistent ambiguity is investigated using its latest
   evidence; a resolved transient needs no LLM report. Numerical warnings and
   manual review never wait. In **Automatic investigation**, distinguish simulated
   source UTC from actual queue/report UTC. Replay speed accelerates the source,
   not the LLM.
4. Pause when the supported interval appears. Review the report and its original
   evidence. A newer material warning can wait for bounded dispatch while an older
   investigation is retained; historical reports are labeled, never silently
   rebased. Failures withhold reports without clearing numerical warnings.
   Minor quality changes still update the dashboard, but do not alone queue an
   identical physical investigation. A changed hypothesis, affected segment,
   material location or lost/recovered coverage remains a dispatch trigger.
5. Open raw records, compare histories or ask a question to **pin** an immutable
   window. The independent stream keeps running; **Follow current** resumes the
   live inspector. Detection criteria and provenance remain available in the
   expandable details, and full agent receipts remain in Agents.

The three suggested questions are "Leak or faulty sensors?", "Where should we
inspect, and why?", and "What evidence supports this, and what remains unknown?"
This is a five-minute handover design, not a measured human-usability result.
The 300s report budget starts at admission. Source-time triage, wall-clock queue
time and source-to-warning/report latency are distinct; accelerated replay does
not establish a field response-time guarantee.

At the mature S1 window, nearby pressure drops support inspection of **P1,
200-600m**, while a separate faulty sensor is still reported. Compare S2's
scattered spikes, missing data and drift. S3 demonstrates a source outage; S4 a
broad pressure change requiring operating-context review, not a localized leak;
S5 an unobservable leak with inadequate coverage; S6 normal variability.
The brief and console share an upright Y: Trunk P1 below, Branch A P2 to the
left and Branch B P3 to the right. Each 800m pipe has stations at 100/300/500/700m,
with A/B pressure taps on opposite walls of an assumed 0.6m pipe. Paired taps
share a gateway and are not independent witnesses. Their wall offsets are
enlarged only for readability; A/B wall sides match the brief. The amber line marks
only the computed inspection interval, not the whole pipe. **Compare event / fault
sensors** supplies a default selection when no custom instruments are checked,
opening actual same-window histories on common pressure and UTC axes; S2 includes drift on the
Trunk, spikes on Branch A and missing readings on Branch B.
Archived source generations are labeled and cannot be replayed as pressure-v3.
No actuator or shutdown endpoint exists.

### Show an adaptive investigation

Create a new S4 replay and pause at source clock 185s. Ask the third customer
question. The numerical result remains **insufficient evidence**, with no leak
location. The diagnosis agent chooses a document search, opens relevant records
and selects a before/after pressure comparison. The synthetic valve log can
support **operating change plausible**, not "no leak."

Open **Agents → Investigation workspace** for the review handoff, readable
source documents and before/after comparison tables. Expand **Execution details**
for task dependencies, actual tool arguments and receipts.
Contrast S2's maintenance-backed instrumentation review, S1's unresolved operating
context despite a supported inspection interval, and S5's missing observations.
These are not unrestricted autonomous discoveries: the agent chooses bounded
read-only investigations; code checks citations, measurements and authority.

The roles do not vote truth into existence. Quality feeds diagnosis, then
response. Code checks numerical claims, scope and authority. New `engineer-v2`
reports additionally pass a **separately prompted grounding critic** that reads
original sources and reviews every answer, cause and verification question.
Code requires complete review coverage and literal source quotes. Criticism
allows one interpretation-only revision and a fresh review; a second rejection,
provider failure, exhausted budget or deadline withholds the report.
The acceptance record binds the exact result and evidence packet; downloads
revalidate it. Expand **Independent grounding review** to inspect findings.

The critic uses the same underlying model, not an independent expert or proof
of correctness. Human review remains necessary; do not promise zero
hallucinations. Archived `engineer-v1` reports remain explicitly unreviewed.
The original failed counterexample is preserved unchanged in
`docs\evidence\interpretation-grounding-audit.json`; new qualification is recorded
separately in `docs\RESULTS.md`, including failed attempts.
The current genuine runs include a false-photograph rejection/revision and a
natural overclaim corrected after the critic distinguished period medians from
sustained response. The six-report qualification cohort took 127-223s; that is
functional evidence, not a field SLO or proof of labor savings.

The corpus is `fixtures\synthetic\operational-history.json`. PostgreSQL full-text
search provides small-corpus RAG without another service or embedding dependency.
Structured pressure history stays in SQL, not a vector index. Future records are
hidden; stale/draft records cannot support a current conclusion. Segment scopes
include their sensors/gateways. Corpus versions
are immutable and pinned to tasks; accepted responses inherit the diagnosis review.
Customer operating/maintenance feeds remain unconnected.

### Ask engineering questions, not just for a classification

The LLM's role is interpretation and RCA context, not replacing the pressure
detector. Try:

- “Could a valve change explain this pressure pattern? What should we verify?”
- “Is there evidence of drift, or are we assuming every anomaly is a faulty sensor?”
- “Why is the inspection area a range rather than an exact leak position?”

New answers open with a question-specific, **model-written engineering
interpretation**, cited competing causes and follow-up verification questions.
The checked numerical evidence remains a separate section. References must resolve
to accepted claims or the specialist's reviewed history. Citation membership does
**not** prove that the prose follows from its sources: the interpretation requires
engineer review and cannot clear safety or establish a confirmed root cause.
Planning reuses a prior review only when its investigated evidence fits the question.

The **investigation handoff** brings the explanation together with the checked
inspection interval or explicit withholding, competing causes, unresolved evidence
and next review step. Click references to inspect actual source text or computed
comparisons. A follow-up button only drafts a question against the original
window; explicitly submit it to request another investigation. Moving to a new
window never silently carries forward an old answer. Explicitly opened historical
answers display a scope warning.

**Download this investigation handoff (JSON)** exports the versioned packet, including exact
task/window identities, source revisions, checked claims, executed checks and fresh
call counts. It is not engineer approval, a work order or safety clearance. Reused
specialists' earlier model calls are not counted as new calls; monetary cost remains
unknown.

```powershell
uv run python scripts\qualify-engineer-questions.py --mode scripted `
  --output runtime\engineer-questions-scripted.json
# Explicit hosted inference; consumes Copilot allowance:
uv run python scripts\qualify-engineer-questions.py --mode live `
  --output runtime\engineer-questions-live.json
```

For an explicit synthetic availability check or live qualification:

```powershell
uv run subsea provider-check --mode live --model gpt-6.1-sol
uv run subsea evaluate --suite agents --mode live --repetitions 1
```

Live calls consume your Copilot allowance and may take minutes. Authentication or
quota failure blocks further live work; it does not stop numerical monitoring.
There is no automatic provider switch/retry. The CLI is local, **inference is hosted**.
The console and qualification pin `gpt-6.1-sol`; choose LIVE before creating a new
generation to demonstrate real inference. SCRIPTED remains an explicit offline mode.
Manual questions are capped at three per operator per minute across generations.
An HTTP 429 requires waiting; creating another generation does not bypass that guard.

## Architecture and verification

CustomerOps-inspired Python/FastAPI + PostgreSQL + original TypeScript/esbuild UI.
LangChain provides the model interface; LangGraph persists interrupt-driven role
workflows in PostgreSQL. Native OpenTelemetry exports bounded asynchronous spans
to self-hosted Langfuse/Jaeger; stored trace visibility is checked separately from
HTTP acceptance.

The lightweight stand-in for existing ML is a fitted **median/MAD one-class
detector**, frozen on verified-normal pre-roll. Each instrument's normalized
pressure deviation is scored against that baseline; no LLM training or heavy ML
package is needed. Production detector integration remains future work.

Numerical code owns unit/time normalization, conflict quarantine, two-sided
anomaly alerts, sustained pressure-drop evidence and topology/time corroboration.
A suspected leak requires at least three instruments at two stations in two
failure domains, with 15s overlapping drops within 400m pipeline distance.
Paired instruments alone do not establish independence. Healthy stations on both
sides bound an inspection interval; its midpoint is **not a predicted leak point**.
Broad changes, brief correlated transients, missing context and poor coverage
retain explicit uncertainty rather than becoming forced leak/fault verdicts. Three
scoped quality/diagnosis/response agents and a tool-free response critic use immutable evidence,
bounded calls and checked claim IDs. The model cannot fabricate accepted numbers.
Monitoring uses 60-second windows, 5-second hops and 5-second lateness, independently
of the inference worker; late evidence creates revisions rather than rewriting history.

Stop the demo server and finish any qualification cohorts before Python integration
tests: their fixtures reapply the owned database schema. Do not run these migrations
concurrently with workers or another test process.

```powershell
. .\tools\load-environment.ps1
uv run pytest -q
uv run ruff check .
uv run mypy src
npm run typecheck
npm run build
uv run subsea evaluate --suite agents --mode scripted
uv run python scripts\evaluate-history-baseline.py `
  docs\evidence\agents-history-scripted.json runtime\history-baseline.json
```

Restart `uv run subsea serve` in another terminal, then run
`npx playwright test --grep-invert "LIVE engineer"`.
Browser qualification requires that server and installed Chrome. Run
`uv run subsea evaluate --suite diagnostics --mode scripted` for the six-scenario
held-out numerical evaluation. Numerical results are in
`fixtures\synthetic\evaluation-results.json`; fresh cohort
receipts go to ignored `eval\results`. Never substitute scripted success for live
qualification or synthetic accuracy for field reliability.

To reproduce sequential warning timing:

```powershell
uv run python scripts\evaluate-warning-timeliness.py --seeds 3 `
  --output runtime\warning-timeliness.json
```

### Evaluate the agent operations, not just detector accuracy

The matched operations benchmark runs **all six scenarios x all three customer
questions** against a quality-aware, zero-LLM report workflow. Both methods use
identical arrival-gated data, numerical snapshots and history. It audits actual
specialist handoffs, model-selected history actions, source authority/timing,
scoped reuse, critic/reflection phases, review attestations, budgets, call
accounting and idempotent resubmission. Raw reports retain every attempted case,
full tool/model receipts, the baseline reports and all-attempt report latency.

```powershell
uv run python scripts\evaluate-agent-operations.py --mode scripted `
  --output runtime\agent-operations-scripted-new.json
# Genuine hosted inference; 18 reports, potentially several minutes each:
uv run python scripts\evaluate-agent-operations.py --mode live `
  --seeds 91000 --output runtime\agent-operations-live-new.json
```

Outputs must be new paths: the evaluator refuses to overwrite an earlier run.
First questions are cold; later questions may reuse validated specialists.
Read [the evaluation protocol](docs/AGENT_EVALUATION.md) for the frozen rubric,
failure denominators and fair latency boundaries. Structured rubric correctness
is not independent prose accuracy. Rules-generated reports may be faster;
agent-assisted savings over human investigation require a timed human study.
The actual hosted first run delivered **15/18** correct reviewed reports
(p50/p95 **129s/170s**), versus **18/18** fixed reports (p50/p95
**0.562s/0.881s**). Three explicit retries passed separately; failures were not
erased. These results do not prove an agent speed or reliability advantage.

The separate warning-timing script releases arrivals before normalization and
scans every 5s hop. It
measures synthetic source-time delay, not sensor-to-human delivery. The browser
suite separately runs a local 1x warning-delivery journey and writes
`docs\evidence\warning-browser-timing.json`. The report-processing target is
300s from question admission to accepted result; UI/human receipt is a separate
measurement. Include failed, withheld and deadline-missed investigations in a
pilot, not only accepted reports.

To explicitly exercise two real hosted-model turns through the browser, including
source review, a generated follow-up and the downloaded handoff:

```powershell
. .\tools\load-environment.ps1
$fixture = uv run python scripts\seed-handoff-replay.py | ConvertFrom-Json
$env:SUBSEA_LIVE_HANDOFF_REPLAY = $fixture.id
npx playwright test console.spec.ts --grep "LIVE engineer"
```

This seeds a paused, mature synthetic S4 window in the normal console tenant,
without automatic agent roots. Both questions use normal authentication, scoping
and rate limits. It consumes Copilot allowance; successful evidence is written to
`docs\evidence\handoff-browser-engineer-v2-live.json`. A scripted browser pass alone does not
qualify this hosted workflow.

To qualify the actual **automatic** stream-to-report dashboard path:

```powershell
. .\tools\load-environment.ps1
$env:SUBSEA_QUALIFY_DASHBOARD_LIVE = "1"
npx playwright test dashboard.spec.ts --grep "LIVE automatic"
```

This creates a real LIVE S1 replay through normal APIs, observes monitoring and
manual trends while hosted analysis is in flight, then checks the automatic
handoff and its grounding review. Every observed root, including failures, is
retained in a new `runtime\dashboard-live-<replay-id>.json` artifact. One successful
journey is functional qualification, not an accuracy or availability estimate.

Use `scripts\seed-handoff-replay.py --scenario S1` to prepare a mature LIVE leak
fixture without automatic model roots. Ask the three suggested questions before
the meeting; present preserved answers as **recorded LIVE**, with their exact
window and receipts, rather than promising three fresh runs in ten minutes.
The prepared examples in `docs\evidence\prepared-s1-live.json` took 88-143s and
all export the supported P1 200-600m interval. New installations must generate
their own console state; the repository contains no database credentials/dump.

Challenge the critic with invented inspection evidence, command/actual-position
confusion, causal overreach, false calibration and unsafe control advice:

```powershell
uv run python scripts\qualify-grounding.py --task-id <accepted-live-S4-root-id> `
  --output runtime\grounding-adversarial.json
```

This uses real source bodies from that console task without modifying its
answer. The authored cohort qualifies the critic separately from the full
author/revision workflow; it is not blind or field validation.

To reproduce the complete critic/revision/re-review challenge on a new,
isolated synthetic S4 workflow (deliberate draft injection, not a real inspection):

```powershell
uv run python scripts\qualify-engineer-questions.py --mode live `
  --inject-unsupported-draft --output runtime\grounding-revision-live.json
```

The pressure hold-out matches all 120 expected mature-window outcomes. All 20
observable-leak inspection intervals contain the simulated source; sensor-fault
attribution still has **three false positives**. These are controlled synthetic
results, not field accuracy. Pressure-only receipts are retained separately;
they do not qualify the new history loop. Current investigation evidence and
baseline comparisons are in `docs\RESULTS.md`. SCRIPTED is not hosted inference.
Separate roles provide bounded authority and audit, not demonstrated accuracy
improvement over one agent.

The controlled scripted comparison matched four contextual expectations with
adaptive retrieval, three with a broad fixed workflow and **four with a
quality-aware fixed workflow using no LLM**. This is not proof agents outperform
rules or graph ML. Buy a bounded shadow pilot only if real investigations show
incremental value after model latency, integration and operating cost.

### Context-sensitive inspection scenarios

The separate inspection-priority lab contains **16 synthetic cases** on the
same Y topology: four development cases and twelve frozen evaluation cases. It compares
numerical-only prioritization, a frozen context-aware deterministic workflow and
genuine hosted interpretation. All receive identical code-computed candidate
intervals and incident-visible records; expected decisions are withheld from
model input.

Cases include cancelled versus executed work, obsolete paperwork headings,
topside versus subsea asset scope, corrected tags, quoted past operations,
single-tap calibration, conflicting logs, future/draft evidence, missing outer
reference stations and concurrent bad samples. The question is **which supported
area needs investigation first**, not whether an LLM calculates better coordinates.
Deprioritization never clears an area of leaks.

```powershell
. .\tools\load-environment.ps1
uv run python scripts\evaluate-inspection-context.py --mode fixed `
  --output runtime\inspection-fixed.json
# Genuine inference: up to 14 model calls; uses your Copilot allowance.
uv run python scripts\evaluate-inspection-context.py --mode live `
  --output runtime\inspection-live.json
```

See `docs\RESULTS.md` and `docs\evidence\inspection-context-live.json` for actual
wins, ties, losses, source text and model receipts. Data/policy/code hashes retain
the comparison's identity. This is an author-created evaluation, not independent
customer validation; "held out" does not mean an externally authored blind test.
The first hosted run matched **15/16** priority sets versus **12/16** for the
context-aware fixed workflow, with four wins, one conservative loss and zero
unjustified demotions. This is an inspection-priority comparison, not better leak
coordinates. The lab is separate from the console's six replay scenarios and does **not**
override its physical diagnosis/location gate. A better deterministic parser or
structured execution data may close any measured interpretation gap.

See [the one-page submission brief](https://github.com/ntnguyen-so/subsea-integrity-copilot/blob/main/docs/SUBMISSION_BRIEF.md),
[engineering report](https://github.com/ntnguyen-so/subsea-integrity-copilot/blob/main/docs/REPORT.md)
and the retained milestone/design plans in `docs`. Inspection intervals follow
station support, not inverse hydraulic localization or calibrated confidence. Human
integrity engineers retain inspection and safety authority.

Email `docs\SUBMISSION_BRIEF.pdf` (exactly one page), with the GitHub link,
at least 24 hours before the meeting. Confirm reviewer repository access.
The expanded narrative remains `docs\ONE_PAGE_BRIEF.pdf` (two pages), preserving
the approved customer story and detailed assumptions. Regenerate both with
`node scripts\render-brief.cjs`; it fails if the submission exceeds one page.
Both brief panels and the deck topology are generated from the same
`pressure-pack-v3` geometry used by the console. Rendering regenerates
`fixtures\synthetic\brief-evidence.json` from actual mature S1/S2 snapshots and
observations, then draws those sensors and pressure histories—not a separate
illustrative dataset. Tests check source coordinates, sensor identities, quality
patterns and numerical conclusions. Display offsets are exaggerated; the diagram
is not a geographic scale drawing.

## Interview deck

The deck follows the current pressure demo and the brief's three questions.
Historical acoustic receipts remain separately labeled in the engineering report;
they are not pressure-version evidence.

Open `docs\INTERVIEW_DECK.html` directly in Chrome or Edge; no server is required
for the presentation. `docs\INTERVIEW_DECK.pdf` is the widescreen audience export.
Keep `docs\assets` alongside the HTML when copying the presentation.
Its evidence/code links point to GitHub rather than this computer's local paths;
reviewers need private repository access.
The 18-slide main story follows **5m problem / 10m live demo / 30m technical
whiteboard / 10m business / 5m out-of-role questions**. Four on-demand appendices
do not add scheduled time.

Use Left/Right or Page Up/Down to navigate, Home for the first slide, End for the
out-of-role questions, and **N** for presenter notes. Chapter buttons and the slide
selector jump directly. Start/pause/reset the elapsed interview clock explicitly;
navigation does not reset it. Notes include live-demo steps, whiteboard prompts,
timed handoffs and an honestly labeled recorded-evidence fallback.

The deck is original; CustomerOps informs its customer-first narrative, evidence
chain, scoped specialists, durable execution and explicit tradeoffs. Diagrams are
original SVGs, not copied reference/marketing assets. LIVE measurements and synthetic
limits link to retained receipts; the deck does not introduce new field claims.

```powershell
npm run deck:test
npm run deck:pdf
```
