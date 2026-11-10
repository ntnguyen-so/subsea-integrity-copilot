# Engineering report

[Run the demo](../README.md) · [Operating commands](DEMO_DETAILS.md) ·
[Qualification results and history](RESULTS.md) ·
[Historical agent/fixed benchmark](AGENT_EVALUATION.md)

## Scope and design

Subsea Integrity Copilot helps an integrity engineer investigate pressure alerts:
possible leak, instrumentation/telemetry issue, operating change or unresolved
evidence. It proposes review priorities and explains supporting measurements,
sources and uncertainty. **All data are synthetic. This is read-only decision
support, not a safety system, validated hydraulic model or production deployment.**

The customer and buyer roles in the brief are fictional. Existing detectors and
manual investigation are the baseline, not an invented inferior competitor.
The product hypothesis is that reusable advisory knowledge and selective evidence
gathering can improve review and handover. Field reliability, human-effort savings
and superiority over a strong fixed workflow remain unproven.

## Architecture

```text
Seeded or frozen synthetic raw records + separate verified-normal baseline
  -> arrival-gated canonical buffer (UTC, units, validity, provenance)
  -> independent monitor: 60s windows / 5s hops / 5s lateness allowance
  -> immutable PostgreSQL measurement snapshot and evidence ledger
       |
       +-> immediate numerical warnings -> SSE + TypeScript console
       |
       +-> admitted investigation root
            -> Sensor Quality -> Event Diagnosis -> Operator Response
            -> source-grounding review -> bounded revision or withholding
            -> checked handoff + separate quoted report-to-map extraction

PostgreSQL business tasks/leases/receipts govern execution.
LangGraph checkpoints recover graph conversations.
Optional OpenTelemetry -> local Langfuse/Jaeger observes execution.
```

FastAPI/Pydantic define API and data boundaries; NumPy owns measurement arithmetic.
The TypeScript/esbuild browser presents server evidence and never performs model
inference. PostgreSQL uses forced tenant/site row-level security, separate
application/read-only-tool roles and a separate checkpoint schema/owner.
Local operator login uses Argon2 verification, signed sessions and CSRF checks.
This is not production multi-user identity or an HA scheduler.

Every admitted root gets its own worker/checkpointer context. Dependencies within
that root remain ordered; parallel roots improve throughput, not the critical path
of one report. Call reservations, leases, deadlines, immutable scope and receipts
are persisted; no SQL transaction spans inference. Generation-serialized event
writes and coherent projections support durable SSE reconnect cursors.

## Data handling and numerical sources

`synthetic.py` declares illustrative signal/fault recipes. S1-S6 use three 800m
segments with 12 paired stations and 24 instruments. S7 uses seven 1600m segments,
56 paired stations and 112 instruments. Coordinates are local metres, not GPS.
Paired taps share a gateway; two instruments are not automatically two independent
witnesses. The pressure footprints are not calibrated gas hydraulics or pressure-
wave arrival-time simulations.

`ingest.py` converts declared units to bar and explicit zoned timestamps to UTC,
retaining original payloads and transformation records. Unknown formats, malformed
values and impossible domains are not guessed into usable measurements. Exact
duplicates are retries; different payloads with the same source identity quarantine
all variants. Missing or excluded readings remain auditable and are not imputed.

`diagnostics.py` uses half-open event-time windows and only observations received
by the pinned source clock. Late evidence may create a new revision inside the
configured horizon, never rewrite the earlier snapshot. Hashes bind observations,
normal reference, geometry and policy; agents and exports keep that basis.

| Number | Source and interpretation |
|---|---|
| Pressure anomaly score | `anomaly.py`: `(value - normal median) / max(1.4826 * MAD, minimum scale)`. Fitted only on separate verified-normal data; not a leak probability. |
| Coverage | Distinct usable timestamps divided by expected samples across instruments; invalid/missing rows cannot improve it. |
| Pressure changes and profiles | `diagnostics.py`, `history.py`, `profiles.py`: labelled reference periods, medians, usable counts, extrema and adjacent steps. Five-second, twenty-second and historical comparisons are not interchangeable. |
| Correlation and distance | Paired-complete Pearson correlation with shared-sample counts; missing/constant/insufficient series stay unknown. Distances follow connected pipe endpoints, not geometric crossings. Correlation is not causal independence. |
| Replay time | A simulated source clock. Speed changes observation playback, not hosted inference duration. |
| Latency and usage | Persisted task/model receipts. Queueing, accepted-report completion, separate mapping and active human handling are different clocks. |
| Displayed USD estimate | `execution_usage.py`: labelled API-equivalent scenario using dated rates and reported usage, not actual Copilot billing or measured savings. Unknown usage stays unknown. |

Cadence, window/hop/lateness, anomaly threshold and minimum scales are declared
demo policy in `contracts.py`, not learned reliability figures.

### Monitoring is not agent diagnosis

Fresh agent-assisted investigations use `llm-diagnosis-v1`. Their windows use
`screening_only=True`: numerical code supplies measured alerts, counts, profiles
and metadata, **not a preselected cause or inspection answer**. The agents reason
about those measurements, actual records and topology.

The fuller deterministic event and localization helpers remain for legacy and
evaluation paths. Their persistence/coverage/observer gates and station-midpoint
brackets must not be presented as the fresh model's decisions. `localization.py`
documents those heuristics; a bracket is neither a hydraulic leak coordinate nor
a confidence interval. Archived tasks retain their original policy.

Numerical warnings continue without inference. Missing-only coverage loss does
not establish a hardware fault, no-leak state or physical pressure event.
Automatic investigation admission and any configured acquisition delay are
measurement workflow controls, not proof of cause. Recordings retain the pause
policy used when they were created.

## Governed investigation and answer checks

The roles collaborate serially rather than voting:

1. **Sensor Quality** reviews measurement reliability and coverage. Its bounded
   review cannot certify every instrument or establish a physical cause.
2. **Event Diagnosis** consumes that accepted handoff, compares pressure patterns
   and selects bounded history searches, full document reads and measured
   before/after comparisons.
3. **Operator Response** synthesizes a diagnosis-first report with competing
   explanations, explicit instrument findings, inspection priority if supported,
   limitations and verification steps.

`runtime/registry.py` defines capabilities; `runtime/gateway.py` executes scoped
reads and records receipts. Mandatory intake is application-owned and attributed
as such, not counted as autonomous model discovery.

Operational history and advisory knowledge have separate authority:

- **Operational records** are fictional, versioned and incident-time filtered.
  PostgreSQL lexical full-text search discovers sources; full reads establish
  what may be cited. Draft, expired, superseded and future material cannot become
  current authority. Backend scenario tags never become agent diagnosis labels.
- **Advisory knowledge** contains reviewed-for-demo heuristics/procedures,
  prerequisites, counterexamples and limitations. Exact applicability, declared
  conflicts and supersession control selection. A pinned packet is inherited by
  specialists; it is not an observation or pipeline-SME approval.

`validation.py` checks schema, scope, role authority, actual source reads,
references, dependencies, inherited limitations and protocol requirements.
These are deterministic safeguards, **not proof that prose entails its sources**.
Retrieved text is evidence, never authority to run instructions or control assets.

Fresh `semantic-grounding-v2` review uses a separately prompted, tool-free model
against the original source material. Its record binds task/question, candidate
and source-material hashes and covers every explanation unit. Rejected units
receive source-bound corrections; up to three interpretation revisions are
allowed, stopping immediately on acceptance. Supported checks may be reused only
when the unit and complete source bytes are unchanged. Final coverage remains
mandatory. Provider failure, exhausted budget or unresolved rejection withholds
the report. Archived `grounding-v1` reviews retain their exact-quote protocol.

The reviewer may use the **same underlying model**, not an independent engineer.
Common-mode reasoning errors and unsupported interpretations remain possible.
Citation membership, literal quotation and model agreement each have limits;
human review is still required. Historical grounding failures remain published.

### Execution and model transport

The current root deadline is 900 seconds, individual model requests 180 seconds,
with shared root ceilings of 30 model and 54 tool calls. Per-role allowances are
in `runtime/registry.py` and database guards; `budgets.py` owns shared bounds.
Retries and failed calls consume persisted allowances. These are resource caps,
not latency guarantees or a reliability score.

The pinned Python SDK keeps one owned, installed Copilot CLI runtime warm.
Each inference creates/deletes a separate session with native tools disabled;
application tools remain behind the gateway. Inference is hosted, not local-only.
The explicit `SUBSEA_COPILOT_TRANSPORT=cli` setting selects the older per-call
subprocess adapter. There is no automatic fallback or hidden replay of failures.

Prompts live in `src/subsea_copilot/prompts/` with declared versions and hashes.
New investigations pin a frozen catalog across handoffs; another release cannot
silently resume that work. Finish active investigations before deployment.
Observability records public checks and receipts, not private chain-of-thought.
Synthetic content capture requires explicit opt-in; stored trace verification is
separate from exporter acceptance.

## Handoff, maps and recorded playback

`casefile.py` assembles a review packet from revalidated results and executed
sources. It retains task/window identities, input/configuration versions, reviewed
documents, comparisons, limitations, review provenance and fresh/reused work.
It is not engineer approval, a work order, leak clearance or dispatch authority.

Cause, instrument and inspection overlays come from a separate truth-blind
extraction of the accepted coordinator report, with original quotations and
validated asset/interval references. Numerical flags do not fill missing model
findings. Mapping has separate receipts and can fail without erasing the report.

`playback.py` binds saved reports to raw-data hashes, geometry and immutable
windows. Playback only reads stored reports/mappings and reconstructs measurements
at their original arrival cutoff. It never starts inference or paints a future
finding onto earlier data. Reviewed abstentions and failed attempts remain
visible; missing/unverified traces are not replaced with another run's trace.

## Evaluation boundaries

Use [RESULTS.md](RESULTS.md) for published outcomes, exact cohorts and retained
failures, not numbers copied from an older specification. Raw evidence in
`docs/evidence/` is deliberately retained; some is also consumed by the application.
Local runtime libraries, full reports and trace services are not all bundled.

| Evaluation | What it establishes, and what it does not |
|---|---|
| Unit/integration/browser tests | Software invariants, recovery, scope and UI behavior. Scripted models/fault injection are not hosted reasoning trials. |
| Detection/reference/spatial evaluation | Deterministic comparison of actual report findings against predeclared synthetic labels hidden from agents. Failures, missed findings and withheld truth-leak intervals remain in denominators. |
| Answer-quality evaluation | Authored factual-reference checks plus separate advisory model ratings. Ratings are opinions, not engineer-validated accuracy. |
| Matched fixed-versus-agent workflow | Historical structured-report and operational comparison on identical evidence. The stronger fixed workflow's wins and all first-attempt failures remain visible. |

Different checkpoints/seeds of one synthetic event are not independent field
events. A development/held-out designation does not imply independently authored
or developer-blind data. Do not combine numerical detector performance, model
extraction, grounding opinions and independent human correctness into one score.
No cohort establishes field sensitivity, a production SLO or labor savings.

## 30-minute technical code route

Draw **measurements → immutable window → governed investigation → checked
handoff → browser**, with hidden-label evaluation on a separate path.

| Time | Code and discussion |
|---|---|
| 0-5 min | `api.py`, `monitoring.py`, `store.py`, `migrations/`: independent loops, immutable scope, task leases and SSE. |
| 5-11 min | `synthetic.py`, `ingest.py`, `contracts.py`, `diagnostics.py`: source assumptions, dirty data, timing, normalization and ledger hashes. |
| 11-18 min | `runtime/workflow.py`, `runtime/gateway.py`, `history.py`, `validation.py`, `grounding.py`: dependencies, evidence selection, checks and residual model risk. |
| 18-24 min | `anomaly.py`, `profiles.py`, `localization.py`, `evaluation_metrics.py`, `execution_usage.py`: formulas, units, denominators, legacy heuristics and estimates. |
| 24-30 min | `casefile.py`, `playback.py`, `web/ts/console.ts`, corresponding tests: exact-window handoff, recorded versus live, failures and what remains unvalidated. |

## Commercial and meeting contract

**Decision now: pilot-design discussion, not production approval.** Propose four
weeks of read-only shadow evaluation on one pipeline **after readiness acceptance**:
data/replay checks, independent expert adjudication, operator comparison and joint
review. Integration/discovery precedes this evaluation clock.

The following are proposed negotiation gates, not customer agreements, a vendor
quote, a statistical power calculation or field certification:

| Gate | Proposed measurement |
|---|---|
| Cases | At least 20 distinct event-level cases, including independently adjudicated observable leaks, instrument errors, benign operating changes and inadequate coverage. Multiple checkpoints of one event do not supply independent field cases; this floor cannot certify sensitivity. |
| Comparator | Blinded/counterbalanced manual, strong-fixed and agent workflows on matched evidence. Record preparation, blocking wait, active review, corrections, retries and handoff separately. |
| Incremental value | At least 20% lower median active human handling than the stronger comparator without increased adjudicated missed/false findings, unsafe recommendations or incorrect clearance. Report uncertainty; prefer the fixed workflow if equivalent. |
| Evidence and safety | Zero observed unsupported safety-critical claims, leak clearances or unauthorized actions in released reports; snapshot-bound support for locations. Keep failed/withheld work and unobservable leaks counted. An observed safety-critical breach stops the pilot for review. |
| Completion | At least 90% of all admitted first attempts reviewable within 900s; disclose retries/failures and median/p95 completion. Warning delivery is a separate customer-defined budget. Five minutes is an aspiration, not a promised gate. |
| Cost and exit | Signed total-spend cap; no automatic paid extension or production-safety rollout. Insufficient labels/cases or inconclusive results mean extend by agreement or stop, not pass. |

Name customer owners for integrity/safety approval, instrumentation/historian
data, operating records, knowledge curation, security/retention, delivery/support
and the sponsor's cap/exit decision. Require approved read-only feeds, geometry,
sensor/gateway metadata, synchronized histories, independent labels, operating
and maintenance records, and hosted-data authorization.
Production connectors, identity integration, expert-approved procedures and field
calibration are not supplied by this demo.

```text
Pilot TCO = attributable actual Copilot entitlement + incremental usage/overages
          + hosting/storage/network/observability + integration/deployment labor
          + customer expert/reviewer labor + support + agreed contingency
```

Rates, customer effort and commercial entitlement remain unknown until discovery.
Model/tool counts are workload counters, not a bill. Do not add a hypothetical
API-equivalent estimate to actual Copilot charges or call freed capacity cash
savings. The manual-time baseline is unmeasured; ROI and avoided inspections are
not demonstrated.

For a 30-minute buying conversation: 5m problem/objections, 10m the recorded S7
investigation, 10m readiness/TCO/scorecard, 5m conditional next steps and owners.
Do not promise a fresh accepted answer inside the meeting. Humans retain all
safety and inspection authorization.
