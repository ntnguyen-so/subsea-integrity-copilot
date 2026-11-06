# Subsea Integrity Copilot: delivery plan

Status: implementation delivered; integration qualification and private publication
are tracked in `docs\RESULTS.md`. The milestones below retain their original criteria.

The implementation specification is
[`docs\TECHNICAL_IMPLEMENTATION_PLAN.md`](https://github.com/ntnguyen-so/subsea-integrity-copilot/blob/main/docs/TECHNICAL_IMPLEMENTATION_PLAN.md).
It refines this plan around three task-scoped LLM agents and the CustomerOps-style
GitHub Copilot CLI proxy transport.
The required CustomerOps technology stack, sliding-window monitoring, interactive
console and Langfuse integration are specified in
[`docs\REALTIME_STACK_AND_UI_SPEC.md`](https://github.com/ntnguyen-so/subsea-integrity-copilot/blob/main/docs/REALTIME_STACK_AND_UI_SPEC.md).

## 1. The engagement and the decision we want

### Current refinement milestones and completion criteria

| Milestone | Completion criterion |
|---|---|
| Joint-pattern source | S1-S6 unchanged; S7 near/far pressure responses and scattered/infra faults verified across seeds; no forced location. |
| Governed knowledge capture | Versioned guidance/program cards; provenance and synthetic-advisory status; scoped selection, conflicts and immutable child inheritance tested. |
| Knowledge-driven RCA | All-instrument discovery; executed joint measurements; knowledge-to-check receipts; independent regional hypotheses and original-source grounding. |
| Qualification | Matching-input knowledge ablation including failures; timing counterexamples; targeted/regression/UI checks; no invented accuracy or human-time claims. |
| Independent challenge | Engineering and buyer reviews report remaining gaps explicitly; approval is not presumed or coerced. |
| Customer shadow-pilot gate | Approved hosted-data path, scoped connectors, named SME review, blinded held-out strong-fixed comparator, measured total handling time and capped commercial terms. |

### Indicative four-week shadow pilot, not an AITOMATIC quote

One agreed pipeline network; read-only historian and maintenance/operations
exports only. Week 1: data authorization, connector contract and SME knowledge
capture. Week 2: shadow investigations and SME corrections. Week 3: blinded
held-out incidents plus quiet/fault/operating cases. Week 4: quality, total
engineer handling/review time, late/failed cases and cost decision.

Before signing, name the customer integrity SME and instrumentation reviewer,
agree a fixed services fee and hosted-usage cap, approve data residency and
redaction, freeze cases/criteria and define exit/data-deletion terms.
Deliver source-linked casefiles, a versioned knowledge register, the paired
evaluation and a go/no-go recommendation. No automatic actuation or safety
substitution. Human hours and monetary savings are not yet measured; if a
cheaper fixed workflow matches quality and total handling time, recommend it.

**Prospect:** NorthSea Integrity Operations, a fictional mid-sized offshore gas operator
with an existing subsea sensor network and onshore integrity team. This is not a claim
about an actual company, customer, deployment or commercial relationship.

**Problem:** engineers must distinguish a possible pipeline leak from faulty instruments
and unreliable telemetry. Both can generate anomalies. Unnecessary inspection mobilization
is expensive; dismissing a real incident is dangerous. The product is a read-only
investigation assistant, not a leak-protection or shutdown system.

**Users:** the onshore monitoring engineer investigates; the subsea integrity lead reviews
the evidence and inspection recommendation; an instrumentation engineer investigates
sensor-health issues.

**Unsigned because:** the budget owner doubts the value beyond existing alarm thresholds;
the technical lead doubts false-alarm performance, localization reliability, data
sovereignty and integration effort. Their alternative is the existing dashboard plus
manual investigation, not an invented inferior competitor.

**Meeting close:** seek a bounded, paid, read-only shadow pilot on one pipeline network,
subject to agreed data access, evaluation criteria and commercial terms. Do not ask the
customer to trust a safety-critical production deployment based on synthetic data.

**Why this problem:** the supplied thesis establishes relevant marine data-quality,
sensor-fault and interpretable anomaly-detection work. Slide 47 motivates combining
local anomalies with network context. This demo adds spatial event diagnosis and
localization; it does not claim these additions were validated by the thesis.

## 2. Evidence used and what it does not establish

| Source | Design implication | Boundary |
|---|---|---|
| Defense deck, slide 47, "Embedded AdapAD + Green Edge AI" | Combine distributed sensor observations with data-quality context. | Concept illustration, not a calibrated deployment map or leak-localization result. |
| Supplied pipeline picture | Build an original schematic with sensors around connected pipeline segments. | No coordinates, lengths, sensor specifications or operational data can be inferred from the picture. |
| Thesis, PDF pp. 28-29 | Preserve accuracy, currentness, completeness, consistency and provenance separately. | Quality-code meanings depend on the source standard. |
| Thesis, PDF pp. 37-38, 233-234 | Expose per-channel contributions; evaluate detection and attribution separately. | A high contribution score is not proof of physical cause or a calibrated probability. |
| Thesis, PDF pp. 163-164 | Leak-related use cases have strict timeliness, completeness and consistency needs; acoustic signals have environmental confounders. | The cited requirements are research-context findings, not this prospect's signed requirements. |
| Thesis, PDF pp. 198-199, 207 | Use explicit normal ranges and verified-normal history; keep missingness out of physical-event evidence. | AdapAD has specific training, regular-sampling and gap-handling assumptions. The MVP is not an AdapAD reproduction. |
| Thesis, PDF p. 240 | Sensor diagnostics depend on prior knowledge; the initially selected detector can miss important faults. | MuMSAD's ROV example does not establish automatic leak diagnosis. |
| CustomerOps deck, pages 4-7, 9, 17-21, 24-28 | Scoped tools, specialist contracts, bounded execution, checked results, replay-safe records, shared derivations and honest measurements. | Reuse architectural patterns, not the entire implementation or historical performance figures. |
| AITOMATIC website, accessed 2026-11-05 | Domain knowledge, governed tool execution and evidence-led improvement belong outside unrestricted model authority. | The public oil-and-gas pack is explicitly directional. No DanaOS SDK, platform deployment or supported connector is established here. |

Public references:
- https://www.aitomatic.com/
- https://www.aitomatic.com/domains/oil-and-gas-operations

Local source files:
- `C:\Users\thanh\Desktop\aitomatic\public_defense_v3.pptx`
- `C:\Users\thanh\Desktop\aitomatic\phd_thesis_for_print-medomslag.pdf`
- `C:\Users\thanh\aitomic\customerops-interview-deck.html`
- `C:\Users\thanh\Downloads\AITOMATICSenior Forward-Deployed Engineer (FDE) - SF  (1) (2).pdf`
- `C:\Users\thanh\customerops\docs\architecture.md`

All thesis page references above use the PDF viewer's 1-based page count, not printed
article pagination. Publish only original code, synthetic fixtures and concise source
attributions. Do not copy employer data, private CustomerOps fixtures, the thesis,
the defense deck or third-party artwork into the private repository.

## 3. Scope and realistic questions

The MVP must answer these questions through the same evidence pipeline, not through
scenario-specific canned answers:

1. **"The alarms started together. Is this a possible leak or an instrumentation issue?"**
   Show coherent nearby physical measurements, persistence, sensor health and competing
   explanations. Return `suspected_leak`, `sensor_or_telemetry_issue`,
   `environmental_disturbance`, `no_event` or `insufficient_evidence`.
2. **"Which pipeline section should our integrity engineer inspect first, and why?"**
   Return segment ID, chainage estimate, compatible chainage range and supporting
   observations, or explicitly withhold localization. Never call the estimate a
   confirmed leak location.
3. **"Which sensors are unreliable, what evidence is missing, and what should we do next?"**
   Identify missing, stale, spiking or inconsistent channels. Recommend read-only
   verification steps under the customer's existing procedure; do not send work orders,
   mobilize a vessel, change thresholds or command a shutdown.

A fourth rehearsal question, **"Does simultaneous missing data prove a leak?"**, must
demonstrate the distinction between measurement absence and physical evidence.

### Must have

- Original synthetic pipeline network and reproducible sensor time series.
- At least three operator questions and a usable local visual demo.
- Server-owned simulated real-time monitoring: a 60-second window sliding every
  5 seconds, with warm-up, lateness and lost-coverage handling.
- CustomerOps' PostgreSQL/Python/TypeScript stack and an original AITOMATIC-console-
  inspired UI with real replay controls and sensor/evidence/task drill-down.
- LangChain model/tool interfaces, LangGraph/PostgreSQL execution checkpoints and
  self-hosted Langfuse attempt/generation/tool/guardrail observability.
- Actual defects: missing observations, spikes, mixed timestamp/unit formats and a
  conflicting duplicate record.
- Three task-scoped LLM agents over deterministic/statistical diagnostic modules.
- Typed structural vocabulary and versioned executable diagnostic rules.
- Raw-to-answer provenance, independent acceptance tests and a reproducible evaluation.
- One-page brief, short run README, verified accessible GitHub link and meeting script.

### Deliberately not in the eight-hour MVP

- Actual DanaOS integration, trained AdapAD/MuMSAD, edge firmware or real subsea sensors.
- CFD, acoustic source triangulation from waveforms, pressure-wave modeling or certified
  leak detection. Ambient seawater pressure is not pipe internal pressure.
- HA/distributed deployment, Kafka, cloud hosting or customer SSO. Local session/role/
  CSRF checks and forced PostgreSQL RLS are required, not production certification.
- Arbitrary replay seek, adjustable window sizes, cosmetic console motion and advanced
  dashboards; core play/pause/step/speed and evidence drill-down are not optional.
- Automatic maintenance, operating changes, shutdown, external notifications or learning
  new thresholds during an incident.
- An unrestricted multi-agent platform. The MVP has three scoped agents and serial,
  persisted handoffs, not a general-purpose swarm or distributed agent platform.

## 4. Data contract and experiment design

### Synthetic operating world

Start with three connected pipeline polylines totaling approximately 2.4 km in a local
metric coordinate system. Place 12 monitoring stations along them, with two synthetic
sensor nodes per station on opposite sides of the pipe: 24 nodes total. Geometry,
station spacing, seabed depth and instrument independence are explicit fixture
assumptions, not quantities measured from either source image.

Channels: acoustic leak-band **relative power in arbitrary units**, dissolved methane
concentration in `umol/L`, and temperature in `degC`. Acoustic power is a simulated
feature, not a calibrated hydrophone level or a sound-pressure measurement. Methane
supports a gas-leak hypothesis only for this fictional gas pipeline. Temperature is
environmental/quality context, not independently sufficient leakage evidence.

Use one-second sampling over a continuous replay and a separate verified-normal
baseline. Generate channel-specific noise, realistic missingness and persisted events.
Methane response can be delayed relative to acoustic response; document its synthetic
lag. Do not assume all physical modalities trigger on the same sample.

### Canonical records

`Observation` contains `site_id`, `sensor_id`, `channel`, `observed_at_utc`,
`received_at_utc`, `value`, `unit`, `source_id`, `source_record_id` and quality/provenance
fields. `Sensor` contains position, associated station, coverage, channel capability
and `failure_domain_id`. `PipelineSegment` contains endpoints, polyline and chainage.

Keep three different concepts separate:
- **Validity:** absent, malformed, stale, conflicted, physically impossible or usable.
- **Anomaly:** a usable value differs from the verified-normal baseline.
- **Hypothesis:** the joint evidence supports a physical event or a data-quality issue.

Missingness may be anomalous for instrument monitoring but is never a measured methane
or acoustic excursion. A large usable value is not discarded simply because it is
anomalous; doing that would erase the leak evidence.

### Defect handling

| Problem | Required handling | Evidence shown |
|---|---|---|
| Missing row, blank or documented sentinel | Preserve null/missing flag; do not replace with zero or use imputation as event corroboration. | Expected versus received samples, affected channel and time window. |
| Isolated spike or sustained sensor drift | Separate pattern/health suspicion from hard invalidity; compare independent neighbors and channels. Do not silently clip. | Original values, residuals, duration and counterevidence. |
| UTC ISO timestamp versus explicitly zoned local format | Parse with declared adapter rules; retain original text; reject an unknown timezone. | Normalized UTC and transformation record. |
| Methane `nmol/L` versus `umol/L` | Convert using an explicit channel-compatible mapping; `1000 nmol/L = 1 umol/L`. Reject unknown units. | Original and canonical value/unit. |
| Same identity with different payload | Quarantine the conflict and record both hashes; no last-write-wins overwrite. | Identity, conflicting records and why excluded. |
| Late or out-of-order telemetry | Analyze by observation time; make ingestion time and freshness visible. A later snapshot may change the assessment. | Snapshot/version and late-record marker. |

Diagnostic code must not read evaluation labels, injected fault names, leak coordinates
or scenario IDs as features. Store these in a separate evaluation-only manifest.
The UI may select a replay, but selection cannot supply a diagnosis to the agent.

### Frozen scenarios

| ID | Scenario | Expected conclusion |
|---|---|---|
| S1 | Persistent localized acoustic increase plus nearby methane response; some background defects elsewhere. | Suspected leak and bounded localization when enough independent measurements remain. |
| S2 | Spatially scattered dropouts, isolated spikes and one drifting channel. | Sensor/data-quality issues; no supported leak localization. |
| S3 | Simultaneous outage across nodes sharing one telemetry gateway. | Common telemetry issue; loss of coverage, not evidence that the pipe is safe. |
| S4 | Broad environmental acoustic disturbance without methane corroboration. | Environmental explanation or insufficient evidence; no invented leak confirmation. |
| S5 | Local physical signal with too few healthy independent observers or conflicting metadata. | Insufficient evidence; request verification and withhold precise localization. |
| S6 | Verified-normal operation with ordinary variability. | No detected event in the observed window, not a guarantee of no leak. |

In S1, also test removal of one supporting sensor. The result must retain the leak
hypothesis only if its remaining evidence still passes the same criteria. Sensor
malfunction and a leak are allowed to coexist; report health findings in every case.

## 5. Reasoning and localization

### Transparent baseline

Use per-channel median/MAD residuals from verified-normal data with a channel-specific
minimum scale to handle constant baselines. Return original magnitude and residual
contribution. These are anomaly scores, not calibrated event probabilities.

Proposed initial demo rule: persistent excursions in at least three usable observers
across at least two independent failure domains, in a local pipeline-associated
neighborhood, with acoustic evidence and nearby methane corroboration within its
declared lag window. Exact thresholds, neighborhood distance and persistence duration
are configured and frozen using development fixtures before held-out evaluation.

Inspect event-time overlap, spatial extent, channel agreement, expected background
variability and known gateway dependencies. Counts of different sensor IDs alone do
not establish independent evidence. Independence metadata is an assumption to verify
with the technical stakeholder.

**Do not use "simultaneous = leak; scattered = faulty" as a sufficient decision rule.**
Shared power/telemetry failures can be simultaneous; currents can spread a real leak
signal; low coverage can make a real event look isolated. The MVP handles these
limitations with explicit competing hypotheses and abstention, not a claim to solve
all their physics.

### Localization contract

Only run localization for a supported `suspected_leak` hypothesis. Restrict candidates
to relevant pipeline polylines and evaluate a 25 m chainage grid.

For the controlled demo, fit the usable acoustic excess powers to an explicitly
simplified distance-decay model:

`predicted_excess_i(s, A) = A / (distance(sensor_i, candidate_s)^2 + r0^2)`

At each candidate, fit nonnegative source strength `A` and compute a quality-weighted
residual. `r0` is a documented softening parameter. Normalize residuals with baseline
noise scales; do not fit on missing/conflicting values. Methane is corroboration,
not input to this acoustic location fit.

Return the best segment/chainage and all candidates within a frozen residual tolerance
of the best fit. Report multiple compatible segments or withhold location when the
fit is poor or the candidate set is too broad. A compatible range is **not a statistical
95% confidence interval**. A 25 m search grid is not 25 m localization accuracy.

Fit against raw canonical excess measurements, not arbitrary anomaly-score magnitudes.
Account for physical proximity and segment association near branches; graph connectivity
alone does not prevent confusing adjacent or crossing pipes. A crossing/parallel-pipe
ambiguity fixture is required even if it is not a primary demo scene.

This idealized model is used to make the chainage computation inspectable. It does
not prove realistic subsea propagation. Held-out simulator variations must change
noise, spread/decay, lag and missingness to expose sensitivity to model mismatch.

## 6. Architecture and agent contracts

```text
Server replay clock / future customer adapter
    -> contract validation + unit/time normalization + conflict quarantine
    -> 60-second sliding window, 5-second hop, lateness/warm-up
    -> immutable canonical window evidence/revisions
    -> quality diagnostics + interpretable anomaly features
    -> topology-aware event assessment -> conditional localization
    -> episode transition + durable console events -> TypeScript/SSE UI
    -> material incident trigger or pinned operator question
    -> scoped evidence/tool gateway (separate agent worker)
    -> quality and diagnosis agent tasks -> response agent synthesis
    -> deterministic answer checks
    -> operator answer + original schematic + evidence/run receipt
```

**Required CustomerOps-aligned stack:** Python 3.11/`uv`, FastAPI/Pydantic/Uvicorn,
PostgreSQL 16/psycopg with forced RLS, `langchain-core`, LangGraph/PostgreSQL
checkpointer, Python-served HTML/CSS/SVG with strict TypeScript/esbuild, and native
OpenTelemetry-to-self-hosted-Langfuse. Use pytest/Hypothesis/Ruff/mypy and frontend
build/type checks. NumPy and optional offline scikit-learn are domain-specific
additions. An inference-only subprocess adapter uses the authenticated GitHub
Copilot CLI, following CustomerOps; no OpenAI-compatible HTTP endpoint or direct
provider SDK is assumed.

The monitor advances independently of LLM latency. Persist window revisions and
episode transitions; trigger agents only on material changes/questions, with bounded
queues and frozen evidence. Show current numerical state separately from older agent
answers. Clock, late-data, replay controls and SSE semantics are in the real-time spec.

Adapt the public console's dark/amber layout, typed-object chips, event pane and
provenance card using original assets/code. The observed website console is a scripted
marketing animation; this UI uses real state transitions, counters and evidence.
No fake confidence/quorum, automatic approvals or auto-switching scenarios.

Bind the demo server to `127.0.0.1`. Deterministic assessments remain available even
if the language model fails; a failed response task must remain visibly failed.
Do not delay existing alarms for model completion or alter existing safety procedures.

The primary demonstration is three live task-scoped agents. An explicit
`--mode scripted` fallback exercises the same contracts without live inference;
it must retain the scripted label, not be presented as live agent reasoning.
Model availability is a milestone gate, not something to conceal with prerecorded text.
The CLI runs locally but proxy inference is not local-only or air-gapped.
Send synthetic evidence only; production data residency/hosting approval is unresolved.

### Three agents, shared runtime and numerical tools

| Contract | Inputs and allowed operations | Output and authority |
|---|---|---|
| Sensor Quality Agent | Request scoped gap/conflict/freshness/pattern tools and interpret their computed findings. | Typed evidence-linked health assessment; code owns hard exclusions and usable coverage. Cannot decide that a leak is impossible. |
| Event Diagnosis Agent | Read accepted quality dependency, measurements/topology summaries and versioned assessment/fit tools. | Select only computed eligible hypotheses and optional location claims. Cannot confirm a leak or change asset state. |
| Operator Response Agent | Propose authorized quality/diagnosis child work or reuse compatible results; synthesize the answer. | Checked claims, limitations and permitted recommendations. No raw SQL, arbitrary file/network access or plant-control tools. |

These are genuine separate LLM tasks with independent contracts, not numerical
functions relabeled as agents. Numerical methods still own scoring, event eligibility
and localization. The parent waits for serial, persisted specialist children and
resumes under a new lease. A compatible saved-summary question avoids new children.
Default model selection is Copilot Auto; explicit available model pins are optional
and measured. See the technical specification for routing, transport and ML tradeoffs.

Structural ontology: `Site`, `PipelineSegment`, `Station`, `Sensor`, `Channel`,
`Observation`, `FailureDomain`, `EvidenceSnapshot`, `EventHypothesis`.
Relations: `located_at`, `monitors`, `connected_to`, `shares_failure_domain`,
`supports`, `contradicts`. Cognitive/procedural knowledge is a versioned set of typed
conditions, evidence requirements, counterexamples, abstention conditions and allowed
recommendations. A text file of domain facts alone is not an executable ontology.

### Harness invariants borrowed from CustomerOps

- Application-selected site, incident, snapshot and rule version are immutable in a
  run; prompt text cannot widen scope.
- Gateway intersects registered role tools with site policy and verifies arguments
  before I/O. A denied call is recorded.
- Bound the root workflow to ten model calls, eighteen tool calls, two children and
  300 seconds across resumptions. Each role has its own smaller budget and at most
  one repair inside that budget; a proxy call is capped at sixty seconds or remaining
  workflow time. These are limits, not latency promises.
- Store incident, requested task, run attempt and accepted result separately.
  An accepted answer does not confirm a leak or close the operational incident.
- Persist source hashes, transformations, evidence IDs, criteria/model versions,
  tool requests, rejection reasons, latency and model usage when available.
- Identical snapshot identity/content is an idempotent replay; different content
  under the same identity is a conflict. Derived results are versioned by input
  hash and rule version. No hidden overwrite of previous evidence.
- The model chooses structured claim IDs and limitations. Shared derivations supply
  sensor counts, timestamps, chainage and costs; the renderer owns numeric wording.
  Validate evidence membership, claim semantics and numeric units, not just whether
  a number occurs somewhere in a cited record.
- Unsupported claims trigger one bounded correction, then explicit failure.
  Missing evidence or model/validation errors cannot become a success-shaped answer.
- A wording-review model is a later extension, not an independent proof of truth.
  MVP release depends on deterministic checks plus independently labeled evaluations.
- Forced RLS and server-side scope checks are tested using the non-superuser app role;
  separate read-only tools/checkpoint ownership follow CustomerOps. A second pack tests
  incompatible mappings and wrong-site access. This is not production/HA certification.
- Langfuse shows actual generation/tool/guardrail attempts through OTel; it cannot
  authorize calls or accept business results. Viewer failure is explicitly degraded,
  not concealed, and current diagnostics continue independently of model/viewer work.

### Intended repository structure, not files already implemented

```text
README.md
pyproject.toml
src\subsea_copilot\
  contracts.py
  ingest.py
  diagnostics.py
  localization.py
  evidence.py
  replay.py
  monitoring.py
  telemetry.py
  llm\copilot_cli.py
  runtime\registry.py
  runtime\gateway.py
  runtime\agent.py
  runtime\workflow.py
  api.py
  cli.py
web\index.html
web\ts\console.ts
web\styles.css
scripts\build-console.cjs
package.json
tsconfig.json
docker-compose.yml
docker-compose.langfuse.yml
fixtures\synthetic\
packs\northsea-gas.json
packs\alternate-site.json
tests\
eval\manifest.json
eval\results\
docs\one-page-brief.md
docs\report.md
```

Prefer small modules around these responsibilities; do not turn every operation
into an abstraction or a separate agent.

## 7. Milestones, dependencies and completion criteria

**Total planned hands-on implementation/preparation: 8 hours.** Source review for this
plan is already complete. Estimates are a scope constraint, not a claim that the
future work is finished. Fit the following stages inside one week; reserve the final
day as calendar buffer and submit at least 24 hours before the actual meeting.
The additional real-time/UI/shared-stack requirements increase estimate risk:
eight hours remains an MVP timebox, not a guaranteed delivery promise.

| Milestone | Effort / suggested day | Depends on | Complete when |
|---|---|---|---|
| M0 - Freeze discovery and safety contract | 0.5 h / day 1 | This plan | Brief/contracts, shared stack and independent PostgreSQL/Langfuse bootstrap ownership; one bounded synthetic Copilot availability/envelope probe recorded. |
| M1 - Generate and ingest imperfect evidence | 1.25 h / day 1 | M0 | 24-node/S1-S6 fixtures, raw/canonical records/separate labels; replay clock/arrivals and immutable sliding windows; defect/replay/conflict tests and original map. |
| M2 - Implement diagnosis and bounded localization | 1.5 h / day 2 | M1 | Continuous attribution/coverage/event/fit; late revisions/episode deduplication; S1 supported location, S5/crossing ambiguity and all-data-loss behavior. |
| M3 - Build three scoped agents and shared harness | 1.25 h / day 3 | M2 | Genuine Copilot tasks/children, PostgreSQL checkpoints, incident-triggered bounded queue, pinned results and actual Langfuse links; scope/replay/failure/budget tests. |
| M4 - Deliver the operator demo | 1 h / day 4 | M2, M3 | TypeScript/esbuild console with moving window/charts/map, play/pause/step/speed, sensor/evidence/task interactions and SSE; truthful current/historical/mode status. |
| M5 - Evaluate and qualify the release | 1.5 h / day 5 | M1-M4 | Frozen/live gate reports, real PostgreSQL RLS/checkpoint tests, stream/reconnect/stalled-proxy/UI checks and actual Langfuse visibility; Python/frontend checks; failures block release. |
| M6 - Package and rehearse the engagement | 1 h / day 6 | M5 | One-page brief and final README; accessible GitHub repository verified; clean-clone run succeeds; 10-minute demo and 60-minute agenda rehearsed; pilot economics and gaps clearly labeled; submission text contains the real repo URL. |

M1's adapter work and M2's calculations are prerequisites to model integration:
do not spend the time budget polishing chat while the evidence pipeline is missing.

### Scope-control rules

If time becomes tight, cut cosmetic motion, arbitrary seek/window-size controls,
advanced ML and optional wording review first. Keep the shared stack, core interactive
sliding-window UI, Langfuse, three questions, defective data, topology reasoning,
uncertainty, scope checks, evaluation and GitHub/run instructions. Remaining mandatory
work is reported as incomplete, not silently demoted to optional.

If the Copilot proxy is unavailable, make the blocker explicit at M0. Use deterministic
diagnostics to complete the analytical backbone, but M3 is not complete and the demo
must not be submitted as a working LLM agent. Do not silently introduce external
providers, retry persistent quota/auth failures, or claim scripted output proves
live-agent behavior.

## 8. Acceptance and evaluation gates

Keep a development set for thresholds and a distinct held-out set: initially 20
independent scenario seeds for each of S1-S6, plus targeted boundary fixtures.
Split whole generated runs, not overlapping windows from the same time series.
Freeze labels and threshold configuration before evaluation. No evaluation labels
are visible to diagnostics or the agent.

Run a simple single-channel threshold baseline on the same frozen inputs and report
its errors alongside the topology/quality-aware approach. This comparison tests the
added diagnostic logic, not a claimed advantage of multiple agents.

| Gate | Measurement / proposed demo target |
|---|---|
| Detection | Event-level confusion matrix for six scenario families; separately report leak precision/recall. Initially target >= 90% recall on S1 and zero false suspected-leak decisions on the mandatory non-leak safety fixtures. These are demo gates, not field reliability estimates. |
| Localization | Segment accuracy; median/p95 absolute chainage error for localized S1 runs; fraction of true locations inside reported compatible candidate sets; abstention rate and candidate-set width. Initially require correct segment and <= 200 m absolute error on at least 18/20 held-out S1 runs. Count withheld locations as failures for this S1 target, not omitted successes. |
| Poor coverage / ambiguity | All mandatory S5, crossing and shared-failure fixtures withhold unsupported precision or confirmation. Zero coverage never implies "pipeline safe." |
| Attribution | Faulty-channel precision/recall and top-k overlap where a contribution ranking is produced. Ground truth for sensor faults is distinct from event ground truth. |
| Agent answers | Run each primary question three times on fixed leak/fault/ambiguous snapshots: 27 answers. Report accepted-correct, unsupported-accepted, false-rejected, legitimate-abstention and failed counts separately. |
| Claim checks | Mandatory rejection of a fabricated sensor, cross-site evidence ID, wrong chainage unit, stale snapshot, "confirmed leak," unsupported savings and "safe to continue production." Supported equivalent unit conversions must pass. |
| Data handling | Missing-as-zero, duplicate overwrite, unknown timezone, incompatible units, shuffled arrival order and one-sensor-removed regressions. Check both valid and invalid examples. |
| Runtime | Record end-to-end latency and failure/timeout counts; include all attempts, not just successes. Record token counts only if supplied; unknown usage is unknown cost. |
| Agent robustness | Unknown tool, denied scope, repair exhaustion and model unavailability fail explicitly. Normal evidence containing instruction-like text cannot grant tool authority. |
| Continuous monitoring | Window boundaries/warm-up, watermark under total outage, late revisions, speed equivalence, preserved replay generations and episode/agent deduplication; stalled proxy cannot stop diagnostics. |
| Console/stream | Replay controls, keyboard sensor/evidence/task drill-down, chart gaps, persistent selection, scoped SSE reconnect/resync and visible current/old-answer distinction. |
| Database/traces | Non-superuser RLS and read-only tool tests, checkpoint scope; actual Langfuse model/tool/guardrail tree and explicit exporter degradation without secrets/private reasoning. |
| Release | `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`, `npm run build`, `npm run typecheck`; independent service/clone startup and three questions. Commands remain intended until implemented/run. |

Thresholds may change after a failed development test, but then version the change and
rerun on a new untouched qualification set. Do not tune on held-out failures and keep
calling the same samples held-out. Do not borrow the thesis's 85% data-quality
requirement as a safety target for operational leak detection.

## 9. Business case, pilot and production transition

Use an inspectable illustrative model, not a fabricated customer ROI:

`annual_triage_value = alerts_per_month * minutes_saved_per_alert / 60 * hourly_cost * 12`

Populate this model only with customer-agreed alert volumes, measured total
handling/review time and actual loaded costs. It is capacity value, not guaranteed
cash savings or headcount reduction. Exclude avoided leak losses and vessel
mobilizations until frequency, cost and attribution are defensible.

The four-week schedule and commercial gates in section 1 are the single current
pilot proposal, conditional on data approval and scheduling. No fixed price,
annual savings or minutes saved have been established. Agree a services fee,
infrastructure/usage cap, integration responsibilities and exit terms before
signing. Report monetary inference cost only with a verified tariff and measured
usage. Any future local model hosting requires a separate production assessment.

Pilot acceptance must be negotiated around operator-reviewed detection/abstention,
false alarms per asset-day, data latency, triage effort and audit completeness.
Rare real leaks may be absent in four weeks: historical labeled events or validated
controlled test evidence are prerequisites to assessing sensitivity. No-leak shadow
data alone cannot demonstrate leak recall.

Production additions: customer-authorized historian/telemetry adapter and real-source
watermark contract; production identity/SSO and distributed queue/worker qualification;
customer-controlled storage/model hosting;
backup/retention and monitoring; versioned ontology release; drift review and rollback.
Existing control and safety systems retain authority. The edge path is a future
bandwidth/energy optimization and must not suppress raw event evidence.

### Multi-account and product-engineering delivery

Keep a reusable core with site-specific adapters, vocabulary, topology, failure-domain
metadata and criteria packs. Onboard a second synthetic site to demonstrate pack
validation, not a fictional second customer engagement.

Use a repeatable discovery -> contract -> replay -> shadow -> qualification cycle.
Maintain per-account decisions, milestone receipts and support boundaries. Review
disagreements with the domain team instead of letting an LLM choose the source of truth.

Prepare three concrete product-gap tickets for the AITOMATIC engineering discussion:
event-time late-evidence handling, spatial/topology computation contracts, and
provenance-preserving numeric output validation. Each ticket needs a reproduction,
impact, workaround, proposed API/contract and qualification test. They are proposed
integration questions, not verified DanaOS defects.

## 10. JD and assignment coverage

| Requirement | Evidence to create / discussion |
|---|---|
| Lead discovery; translate workflows into cognitive ontologies, logic and architecture | M0; structural/procedural vocabulary; three operator decisions; explicit source-authority disagreements. |
| Build production-ready pipelines, integrations, APIs, adapters and reasoning modules | M1-M3; typed ingest, conflict handling, FastAPI, reusable adapters and deterministic reasoning. MVP demonstrates critical components; production readiness remains a pilot qualification claim. |
| Guide deployment, validation and refinement using the platform | M5-M6; clean run guide, release gates and shadow-pilot plan. Actual AITOMATIC platform use is unimplemented and must not be claimed. |
| Collaborate with product engineering; surface gaps and improvements | Three bounded integration-gap tickets with reproduction and proposed contracts; one failure-to-regression story. |
| Reusable patterns and deployment practices across customers | Shared core plus two synthetic packs, wrong-site/mapping tests and onboarding checklist. |
| Expert workshops, design sessions and milestone checkpoints | Technical whiteboard path, stakeholder objections, milestone acceptance and four-week delivery review. |
| 10+ years hands-on engineering experience | Cannot be established by this repository. Use truthful CV/project chronology in the interview; do not manufacture experience. |
| Strong Python or TypeScript engineering | Typed Python/TypeScript, readable numerical modules, strict frontend build/type checks, focused tests and clear ownership. |
| Distributed systems, pipelines, APIs and integration | Continuous event-time windows, late revisions, PostgreSQL/RLS, SSE reconnect, idempotency and leased workers; local processes are not proof of HA. |
| Clear customer engineering/domain communication | One-page brief, operator explanations, evidence drill-down and business/technical walkthroughs. |
| Multiple accounts with structured engagements | Site-pack boundaries and repeated discovery/qualification cycle; no invented concurrent customer history. |
| AI/ML, agents and semantic/ontology modeling | Interpretable features, live bounded tool-calling agent and versioned typed knowledge/procedures. |
| Builder; deep dives and customer collaboration | Working three-question demo, reproducible outcomes and a constrained pilot ask. |
| Resolve ambiguity; clean solutions from domain complexity | Independent sensor-health/event axes, abstention, conditional localization and explicit physical assumptions. |
| Initiative; flag problems beyond immediate scope | Common-mode failure, synthetic-to-real gap, source conflicts, model availability and platform-integration boundaries. |
| Prospect, users and reasons unsigned | Sections 1 and 9; `docs\ONE_PAGE_BRIEF.md`. |
| At least 2-3 realistic questions and imperfect non-confidential data | Sections 3-4; three live questions and six synthetic scenarios. |
| GitHub repo with short runnable README | M6 mandatory gate; real link verified before submission, not invented now. |
| Brief submitted >= 24 h before third round | M6 plus calendar buffer; meeting date is not supplied, so do not invent a deadline or send email. |
| 5/10/30/10/5 minute interview | `docs\REPORT_BACKBONE.md`, meeting outline. |
| One week, approximately 6-8 hours | Seven milestones totaling 8 hours; scope-control rules. |

The JD's location, benefits and compensation descriptions are employment terms, not
demo capabilities. Personal tenure and actual platform experience remain matters for
truthful interview discussion, not boxes a synthetic project can prove.

## 11. Definition of done

Planning is done when the plan, report backbone and prospect-brief draft are consistent
and grounded in the supplied sources.

The **project** is done only after M0-M6 have evidence receipts: the actual agent runs,
the defect-handling and qualification gates pass, the README works from a clean clone,
the GitHub URL is accessible, the one-page brief is finalized and the timed demo is
rehearsed. This plan is not a claim that any of those future gates already passed.
Required technical completion includes continuous sliding-window monitoring, the
CustomerOps-aligned stack, an actually interactive console and visible Langfuse traces.
