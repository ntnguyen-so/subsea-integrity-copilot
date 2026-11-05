# Technical implementation plan: Subsea Integrity Copilot

Status: implemented design specification. Actual measurements and release-gate status
are recorded in `RESULTS.md`; planned criteria below are not themselves test evidence.

This document supersedes the original plan's single-LLM/local-HTTP design. The system
will use **three actual, task-scoped LLM agents**, a shared governed runtime, and
deterministic/statistical diagnostic tools. GitHub Copilot CLI is the only live
inference transport. CustomerOps is the architectural and implementation reference,
not a dependency on another local checkout.

Implementation refinement: mandatory role reads are now audited, application-owned
intake with replay-stable IDs before live interpretation. Real models exhausted the
original pagination budgets; this change preserves 3/4/3 model ceilings and root10,
reserves the final turn, and does not claim model-chosen reads. See `RESULTS.md`.

The required CustomerOps stack, continuous sliding-window monitor, interactive
AITOMATIC-inspired console and Langfuse integration are specified in
[`REALTIME_STACK_AND_UI_SPEC.md`](REALTIME_STACK_AND_UI_SPEC.md).
That specification replaces SQLite and minimally specified replay/UI choices; capabilities remain
planned until implementation and verification.

## 1. CustomerOps decisions we will adopt

The reference was inspected in the current local checkout. Line references identify
the inspected source; they may move as CustomerOps changes.

| Reference | What it actually does | Subsea decision |
|---|---|---|
| Deck pages 4, 17-18; `src\custops\tasks\worker.py:70-104` | Runs separately persisted specialist children serially; resumes a waiting parent under another lease. | Three specialist contracts and real parent/child task records; serial execution initially, not an unrestricted swarm. |
| Deck pages 5, 19-21; `src\custops\tasks\gateway.py:579-677` | Checks context, replay, policy, arguments and budget before executing a scoped read-only tool. | Shared tool gateway with site/snapshot/rule scope and independently enforced permissions. |
| Deck pages 7, 24-25; `src\custops\tasks\agent.py:905-996` | LangChain binds schemas; LangGraph routes model, tool and result-validation nodes. | One reusable LangGraph specialist loop; role-specific prompts/tools/results rather than three bespoke runtimes. |
| `src\custops\tasks\registry.py:39-142` | Defines capability, purpose, tools, required calls and execution/delegation bounds as static contracts. | Typed static registry and explicitly allowed response-to-specialist edges. |
| `src\custops\tasks\handoffs.py:230-316,345-390` | Validates a proposal and creates child/link/wait records outside graph replay; revalidates results on resumption. | Persist authorized child work through the workflow service, not a side-effecting LLM tool or replayed node. |
| `src\custops\tasks\service.py:152-188,768-827` | Requires linked, same-case child results; requeues parents and fences expired workers. | Validate dependency ancestry and scope; compare lease/version before committing outcomes. |
| Deck pages 5, 25-28 | Shares exact calculations, distinguishes grader fixes from agent improvements and discloses failed gates. | Shared numeric claim ledger; positive/negative checker tests; retain failures and unmeasured comparisons. |
| `src\custops\llm\copilot_cli.py:113-235` | `CopilotCLIChatModel` implements LangChain's interface and parses a bounded response envelope. | Independently implement a small equivalent transport contract; no direct provider SDK. |
| `src\custops\llm\copilot_cli.py:237-354` | Starts tool-disabled Copilot in an isolated working directory, sends prompt on stdin and captures JSONL. | Application owns all sensor tools; CLI has no shell, file-write, URL or application-tool authority. |
| `src\custops\llm\copilot_cli.py:654-718,941-1068` | Schemas are prompt text; final values are strings; requested tool calls are decoded into LangChain `AIMessage`s. | Preserve the envelope/inner-result distinction and gateway validation. |
| `src\custops\llm\copilot_cli.py:1071-1192` | Extracts usage without double-counting event sources; model identity can fall back to the requested ID. | Store requested and observed identity separately; unknown usage is null, not zero. |
| `src\custops\web\api.py:405-424`; `src\custops\llm\routing_preview.py:19-26` | Normal live paths construct the adapter without a model ID: Auto selection. | Default all three roles to Auto; optional verified proxy-model pins in site configuration. |
| `tests\unit\test_copilot_cli.py:218-282` | Tests exact flags, isolated environment, stdin and subprocess bounds without live inference. | Equivalent transport-contract tests plus a separately labeled live qualification probe. |
| `pyproject.toml`; `package.json`; `tsconfig.json` | Python 3.11/uv, FastAPI/Pydantic/psycopg, strict TypeScript DOM modules and esbuild. | Same core application stack; NumPy is a disclosed subsea-specific addition. |
| `src\custops\runtime\checkpointer.py:9-19`; `docs\langfuse.md`; `src\custops\telemetry.py:476-574` | PostgreSQL checkpoints and native OpenTelemetry-to-self-hosted-Langfuse tracing. | LangGraph manages execution; Langfuse observes attempts/generations/tools/checks, without owning authority. |

Reference deck:
`C:\Users\thanh\aitomic\customerops-interview-deck.html`.
Reference repository:
`C:\Users\thanh\customerops`.

Important source boundaries:
- `docs\copilot-proxy-setup.md` contains a historical quota failure and blocked
  qualification statement. It is not evidence of current availability; later deck
  pages contain historical live results. Do not conflate these populations.
- Installed CLI help was inspected without inference: version 1.0.105 accepts the
  relevant flags and `--model <model>`, including Auto. Help does not establish which
  model IDs this account can actually use or whether quota is available.
- Do not copy CustomerOps wholesale, import `custops` from a sibling directory, or
  publish its private fixtures. Build an independently runnable repository; any direct
  code reuse requires license and publication-permission review.

## 2. Responsibility boundary: LLM versus numerical methods

The system has two cooperating planes. The **measurement plane** computes findings
reproducibly without an LLM. The **investigation plane** uses LLM agents to select
relevant checks, organize supported hypotheses, explain contradictions and answer
the operator. Existing alarms and safety procedures never depend on LLM availability.

| Work | Default implementation | Why not delegate it to an LLM? |
|---|---|---|
| Schema, units, timestamps, duplicate conflicts | Pydantic and explicit adapter mappings. | Exact, repeatable input semantics; no guessing source authority. |
| Missingness, freshness, completeness, failure domains | Deterministic checks and event-time windows. | Absence is not a physical excursion; correlated failures require declared metadata. |
| Per-channel anomaly features | Verified-normal median/MAD residuals, persistence and peer comparisons. | Fast, inspectable and usable without labeled leakage examples. |
| Event evidence eligibility | Versioned symbolic rules over usable readings, channel agreement, locality and independent failure domains. | A persuasive narrative cannot replace corroboration or change safety criteria. |
| Candidate pipeline location | Noise-weighted distance-decay fitting on measured acoustic excess. | Metres, residuals and ambiguity must come from a declared computation. |
| Choose relevant evidence, explain a quality issue | Sensor Quality Agent using bounded read-only tools. | LLM helps with contextual investigation and explanation, not raw scoring. |
| Compare permitted event explanations | Event Diagnosis Agent using computed evidence and counterevidence. | LLM can synthesize observations, but can select only code-supported conclusions. |
| Interpret the question, request specialists, communicate | Operator Response Agent. | Semantic work routing and audience-specific explanations benefit from language reasoning. |
| Accept claims, render numbers, authorize actions | Application validators, claim ledger and renderer. | Writer self-assessment is not verification. |

### Traditional ML policy

Start with the transparent statistical detector, not a freshly trained neural model.
Expose a `Detector.fit(verified_normal)` / `Detector.score(usable_window)` interface
so an offline ML comparison does not require changing agent or tool contracts.

An optional `IsolationForestDetector` baseline uses window features such as level,
first-difference magnitude, variance and peer residual, with training on verified-normal
development data only. It is a comparison candidate, not the release default:
- It may detect joint patterns missed by separate thresholds.
- Its score is not a calibrated probability and has no inherent trustworthy
  per-channel causal attribution.
- It adds training/configuration/versioning and concept-drift risk.
- Its performance must justify its complexity on frozen held-out runs.

Keep missingness/conflict masks separate from detector features. If a candidate ML
method requires imputation, those estimates never become physical event support.
Do not train on event windows or update the baseline during an incident.

Full AdapAD/MuMSAD integration, AutoML and SHAP are deferred. The thesis informs the
design; this MVP must not borrow its model-performance claims. A future detector is
qualified separately for anomaly detection and sensor/channel attribution.

Compare the single-channel threshold with topology/quality-aware deterministic
diagnostics. Separately compare one LLM agent with governed tools against the proposed
three-agent workflow under the same evidence and acceptance conditions.
Multi-agent execution is chosen for evidence/permission/ownership boundaries,
**not an unmeasured claim of greater accuracy**.

## 3. Three real agents and their contracts

These are distinct LLM tasks with separate prompts, tool sets, budgets and persisted
results. They can use the same underlying proxy-selected model; different roles do
not require different model families or always-running processes.

| Agent / purpose | Allowed tool families | Required evidence | Result |
|---|---|---|---|
| `sensor_quality` / `assess_sensor_health` | `evidence.get`, `quality.coverage`, `quality.conflicts`, `quality.sensor_patterns`, `ontology.neighbors`. | Current coverage/validity report and sensor/failure-domain metadata. | Health classifications with evidence IDs, hard exclusions, soft suspicions and explicit missing information. |
| `event_diagnosis` / `assess_event_and_location` | `evidence.get`, `task.result`, `event.assess`, `event.counterevidence`, `location.fit`, `ontology.neighbors`. | Accepted quality dependency, versioned event assessment and competing explanations; fit result if location is stated. | A supported event hypothesis, optional location claim references, alternatives and limitations. |
| `operator_response` / `answer_incident_question` | `task.result`, `evidence.get`, `criteria.explain`. | Accepted same-scope specialist results or an explicitly scoped abstention. | Operator answer, checked claim references, limitations and allowed next-step IDs. |

Forbidden for every agent: raw SQL, arbitrary file paths, arbitrary URLs, shell,
configuration changes, notifications, vessel mobilization, pipeline control and
cross-site evidence. Agent prompts cannot widen the registry or site policy.

Health outputs distinguish:
- **Hard unusable:** absent, malformed, conflicted, stale or physically impossible.
  Exclusion is computed by code and cannot be invented by an agent.
- **Soft suspicion:** spikes, drift or peer disagreement. An anomaly is not automatically
  invalid. Preserve its measurement and uncertainty so a leak is not filtered away.

Diagnosis can return `suspected_leak`, `sensor_or_telemetry_issue`,
`environmental_disturbance`, `no_event` or `insufficient_evidence`, but the selected
status must be allowed by `event.assess` and its evidence. `confirmed_leak` and
`safe_to_operate` are not allowed states. Sensor faults and a suspected leak can coexist.

Application rules, not the Quality Agent's prose, determine which readings contribute
to physical corroboration. The Diagnosis Agent cannot downgrade a supported event
by declaring its usable high readings "bad sensors" without evidence.

### Authorized delegation

Only the Response Agent may propose these child routes:
`operator_response -> sensor_quality` and `operator_response -> event_diagnosis`.
Diagnosis consumes an accepted quality result as a declared dependency; it does not
inherit the quality agent's tool authority.

A structured work plan uses `reuse`, `quality`, `diagnosis` and `answer` steps.
The application validates the plan before scheduling:
- Health-only question: quality child then parent synthesis.
- Fresh cause/location question: quality child, diagnosis child, parent synthesis.
- Compound cause/location/health question: the same two children, not three repeated
  investigations for three clauses.
- Saved-summary question: reuse only results matching site, snapshot, baseline,
  rule version and procedure; do not create children unnecessarily.
- Missing compatible quality result: insert its required prerequisite or reject an
  invalid diagnosis proposal; never run diagnosis without the dependency.

Maximum child depth is one; maximum children per response is two; one active child
per parent. MVP scheduling is serial. This intentionally follows CustomerOps' current
serial worker rather than claiming parallel specialist execution.

## 4. End-to-end flow and shared agent graph

```text
Replay clock -> canonical ingest -> sliding windows -> continuous diagnostics
                                      |                       |
                         immutable window/revision        console SSE
                                      |
Material incident transition or operator question -> response task -> work plan
                                      |
                         authorize/persist quality child
                         parent WAITING_ON_CHILD
                                      |
                 Quality Agent -> gateway -> diagnostics -> checked result
                                      |
                         requeue/reclaim parent
                         authorize/persist diagnosis child, if needed
                                      |
                 Diagnosis Agent -> gateway -> evidence rules/fit -> checked result
                                      |
                         requeue/reclaim parent
                 Response Agent -> claims/limitations -> answer checks
                                      |
                      guarded finalization -> answer/evidence/task tree
```

Each specialist uses a shared LangGraph:

`START -> model -> tools -> model -> parse_result -> END`

Conditional routes handle tool requests, an accepted result, bounded validation repair
or failure. Save completed tool-call IDs so resumption does not dispatch them twice.
LangChain supplies message types, schema binding and model invocation; LangGraph
supplies routing/checkpoints, not business authority.

The response task's planning/finalization phases are application workflow state around
the shared graph. Child creation, task links, budget reservation and business-result
commit happen in transactional service methods **outside replayed graph nodes**.
Keep graph checkpoints, business outcomes and diagnostic traces separate.

The monitor and agent workers are separately scheduled. A 60-second window advances
every 5 simulated seconds with a 5-second lateness watermark; all-data loss still
advances the clock and exposes lost coverage. Agent work is incident-triggered and
snapshot-pinned, not repeated every hop. Fast monitoring continues during slow or
failed inference. Current telemetry and an older answer's evidence time are visibly
distinct; details and revision/hysteresis rules are in the real-time specification.

## 5. Copilot CLI proxy integration

### Adapter contract

Implement `llm\copilot_cli.py` with `CopilotCLIChatModel(BaseChatModel)`,
`bind_tools`, `_generate` and a bounded subprocess transport. `bind_tools` supplies
schemas as prompt data only. The CLI cannot directly invoke those tools.

Use a fresh request/session ID and empty capture workspace outside the checkout.
Pass a bounded JSON conversation and allowed tool schemas on stdin; never pass prompt
or credentials in command-line arguments.

The reference invocation shape is:

```text
copilot -C <isolated-work-dir>
  --session-id <request-session-id>
  --output-format json --stream on
  --available-tools subsea_no_such_tool
  --no-custom-instructions --disable-builtin-mcps
  --no-ask-user --no-auto-update --disallow-temp-dir
  --deny-tool=shell --deny-tool=write --deny-tool=url
  --log-dir <owned-capture-log-dir>
  [--model <explicitly-configured-available-model-id>]
```

`subsea_no_such_tool` mirrors CustomerOps' empty-tool-set technique. Test the installed
CLI's behavior; a flag existing in help is not proof that tool denial is effective.
Confirm no configured external MCP/custom tool remains accessible. If zero direct
tools cannot be established, fail the live-provider gate rather than granting all tools.

Subprocess controls:
- Resolve the executable locally; use an argument array with `shell=False`.
- Strip inherited parent-session and allow-all/custom-instruction environment controls
  as CustomerOps does. Preserve the owner's normal CLI authentication environment;
  do not copy, inspect or override stored credentials.
- Use monotonic deadlines and bounded stdout/stderr capture. Terminate only the
  adapter-owned process tree on timeout/cancellation, using exact process identities.
- Isolate request capture from customer repositories; remove only owned capture
  directories. Normal Copilot session retention remains governed by CLI behavior.
- Do not scan unrelated Copilot sessions. If metadata requires persisted events,
  read only this invocation's generated session ID, with a size cap.
- Extract the final top-level, non-thinking assistant message; exclude subagent output
  and private reasoning. Public progress is diagnostic only, never an accepted finding.

### Structured response envelope

Tools:

```json
{"kind":"tool_calls","value":[{"name":"quality.coverage","arguments":{},"decision_summary":"Check whether enough recent observations are available."}]}
```

Final:

```json
{"kind":"final","value":"{\"outcome\":\"supported\",\"claim_refs\":[\"claim-coverage-01\"],\"limitations\":[]}"}
```

The outer final `value` is a **string**, matching the CustomerOps adapter. Parse its
inner JSON against the selected role's Pydantic result contract. Valid envelope syntax
is not sufficient for result acceptance.

Require registered tool names, object arguments, allowed envelope keys and fresh
application-generated call IDs. Gateway checks argument fields, site/snapshot scope,
tool budget and ownership independently. Never execute a model-generated command.
Optional public observations reference exact returned call IDs and describe only
already received evidence; they are not hidden chain of thought or an independent audit.

### Models and configuration

Default `requested_model = None`: omit `--model`, matching CustomerOps' usual live path.
All three roles initially use Auto through the existing account. Do not hard-code
a model list from memory or assume that a requested model is available.

Planned configuration:

```toml
[llm]
backend = "copilot-cli"
call_timeout_seconds = 60
max_prompt_chars = 32000
max_final_chars = 12000
max_capture_bytes = 2000000

[agents.sensor_quality]
model = "auto"

[agents.event_diagnosis]
model = "auto"

[agents.operator_response]
model = "auto"
```

Normalize the configuration string `auto` to `None`. Allow explicit role-specific pins
only after the installed CLI/account supports the exact ID and the synthetic probe
passes. Benchmark before preferring a smaller model for quality/response or a larger
model for diagnosis. Different model routing is an experiment, not an automatic upgrade.

Store `requested_model`, `observed_model`, `model_identity_source`, CLI version,
prompt/result hashes, usage and transport timings per call. If identity is only a
requested-model fallback, label it `requested_only`; do not call it observed.
Auto may choose differently on different calls. Reproducible qualification therefore
pins an available model when possible, or explicitly reports that selection was Auto.

### Failure and data-boundary policy

Classify `cli_missing`, `cli_start_failed`, `proxy_auth`, `proxy_quota`, `timeout`,
`empty_response`, `invalid_structured_output`, `invalid_tool_call` and
`output_too_large`. Record sanitized metadata, not raw credentials or sensitive logs.
Auth/quota failures are not retried automatically. Never change subscription/account,
fall back to a direct provider, or disguise scripted output as live inference.

Use synthetic evidence only. **Copilot's CLI runs locally; inference via its proxy is
not local-only or air-gapped processing.** Production sovereignty is an unresolved
deployment requirement until the customer approves the hosting/data route or an
appropriately governed alternative is available.

An explicit `--mode scripted` can exercise contracts and the UI offline; every task,
run, result and answer must retain that label. It cannot satisfy live-agent release gates.

## 6. Diagnostic contracts and ontology pack

Reuse the synthetic data design in `..\PLAN.md`, sections 4-5. Typed records include
`Observation`, `Sensor`, `Station`, `FailureDomain`, `PipelineSegment`,
`EvidenceSnapshot`, `QualityReport`, `AnomalyFeature`, `EventAssessment` and
`LocationFit`.

Every derived record includes site/snapshot/input hashes, method/version, parameters,
units and supporting source IDs. The diagnostic plugin receives a scoped read-only
data interface; a separate service persists its results and audit records.

Core tools return bounded summaries plus evidence IDs, not the full time-series CSV:
- `quality.coverage`: expected/received/usable samples and freshness by channel.
- `quality.conflicts`: quarantined source identities and excluded observations.
- `quality.sensor_patterns`: residual, persistence, peer disagreement and fault-domain
  patterns; hard validity distinct from soft health suspicion.
- `event.assess`: eligible hypotheses, supporting/counterevidence, observer/domain
  counts, temporal/lag overlap and local topology association.
- `event.counterevidence`: known environmental/common-mode alternatives and gaps.
- `location.fit`: candidate residuals, best supported segment/chainage, compatible set,
  fit quality and abstention reason.

`location.fit` must reject a request without a matching, eligible event assessment.
Eligibility depends on computed measurements, not an LLM's preceding status text.
Use acoustic excess in original canonical units for fitting; never fit arbitrary
anomaly scores or imputed values. Preserve disjoint/multi-segment compatible sets.

Ontology pack:
- Structural definitions and typed relations for assets, observations, failure domains
  and evidence.
- Versioned procedures for health, corroboration, abstention, fit compatibility and
  permitted recommendations.
- Native source/unit/time mappings and site-specific thresholds/topology.
- Only a supported set of rule predicates; no `eval`, executable Python from a pack
  or unrestricted natural-language rules as application authority.

Use a second synthetic site pack to test scope, units and topology compatibility.
Pack changes invalidate incompatible results; they never silently relabel old evidence.

## 7. Persistence, idempotency and bounded scheduling

Use PostgreSQL 16 through `psycopg[binary,pool]`, following CustomerOps. Application
tables use forced RLS with transaction-scoped tenant context, server-bound site scope
and a non-superuser role. Read-only gateway connections cannot perform business writes.
Keep foreign keys, short transactions and lease fencing; never hold a transaction
across a model call.

Use `langgraph-checkpoint-postgres` and `PostgresSaver` under a separate checkpoint
owner/schema. Thread/checkpoint identity is server-selected and scope-bound; agents
cannot request an arbitrary thread. Graph storage is not an authorization service.
One monitor and one serial agent worker are the initial local topology, not HA.

| Record family | Required state |
|---|---|
| Evidence | Immutable snapshots/raw hashes, canonical observations, transformations, conflicts, baseline and pack versions. |
| Tasks | Site/incident/snapshot scope, role/purpose, parent, dependencies, state, version, lease token/expiry and input hash. |
| Task links/plans | Authorized proposal, plan step, dependency ancestry, child identity and creation attempt. |
| Runs/model calls | Explicit mode, attempt ownership, requested/observed identity, usage, elapsed time and error. |
| Tool calls | Call ID, bounded arguments/hash, scope, decision, result hash and evidence IDs. |
| Accepted results | Role-validated payload, claim ledger references, input/rule/model versions and status. |
| Monitoring | Replay generation/clock, immutable window revisions, episodes, material-update markers and committed console-event cursor. |

Publish window/task state and UI-event records transactionally. SSE reads committed
scoped events without holding long-lived transactions. Late revisions and new replay
generations retain history; stale results never silently become current assessments.

Task states:
`QUEUED -> RUNNING -> WAITING_ON_CHILD -> QUEUED -> RUNNING -> terminal`.
Terminals: `SUCCEEDED`, `ABSTAINED`, `FAILED`, `CANCELLED`. A supported answer with
no detected event differs from an abstention or infrastructure failure.

Use a uniqueness key for child creation:
`(parent_task_id, plan_revision, step_index)`.
Retry/resumption returns the existing compatible child; changed payload under that
identity is a conflict. Evidence identity uses source/snapshot IDs plus canonical
payload hash. Numerical cache keys include snapshot, baseline, pack, method and
parameter hashes; a saved response additionally binds question/procedure/model policy.

On resumption, validate linked child ancestry, scope, input/version, terminal result
and evidence again. A failed child blocks successful synthesis. An abstained child
may support a clearly labeled insufficient-evidence answer, never a fabricated positive.

Lease ownership is checked before publishing any tool/result outcome. A stale worker
cannot finalize after another attempt claims the task. Parent wait/resume and expired
attempts do not reset counters or the root workflow deadline.

### Initial bounds

| Scope | Hard limit |
|---|---|
| Quality task | 3 model turns, 5 tool calls, at most 1 repair. |
| Diagnosis task | 4 model turns, 8 tool calls, at most 1 repair. |
| Response task | 3 model turns including work planning/resumption/synthesis; 5 tool calls; at most 1 repair. |
| Root workflow | 10 model calls total, 18 tool calls, 2 child tasks, 300 seconds elapsed across children and resumptions. |
| Transport | At most 60 seconds per call, bounded by remaining workflow time; one CLI subprocess at a time. |
| Evidence payload | 12 KiB per tool result; return pagination/summary explicitly instead of silently truncating required evidence. |

Repairs consume existing turn budgets. A parent can resume without another model call
when it only needs to schedule its already authorized next step. Expected simple
child execution is often read-tools then submit-result; maxima are not usage targets.
Measure proxy startup overhead before promising interactive latency.

## 8. Result checking and numeric grounding

Agents submit structured result objects with `claim_refs`, evidence IDs, uncertainty
codes, supported explanation/recommendation IDs and limited commentary.
The numerical ledger owns counts, times, units, chainage and candidate sets.
The renderer produces numeric sentences from that ledger, not from reconstructed
LLM arithmetic.

Acceptance order:
1. Parse transport and role-specific schema; reject unknown fields/statuses.
2. Check role/scope, required tool receipts and accepted dependencies.
3. Resolve cited evidence and claims within the pinned snapshot and version.
4. Validate hypothesis eligibility, validity exclusions and localization prerequisites.
5. Validate limitations and recommendation vocabulary; reject unsupported confirmation,
   control instructions or omission of material ambiguity.
6. Render supported numeric claims with explicit units/rounding and finalize only with
   current lease ownership.

Free text cannot replace these steps. Restrict operational conclusion wording to
supported templates/claim references; optional commentary is not displayed as factual
operator guidance until it passes the same evidence/certainty rules. Open-ended prose
review is a later addition: a second LLM reviewer can catch some overstatement but
adds cost and correlated-error/false-rejection risk.

Regression pairs must accept equivalent supported unit representations and reject
wrong magnitudes, wrong units, supported numbers used for the wrong claim, stale
results and fabricated sensors. Testing only the rejection path can hide a useless checker.

## 9. Modules, APIs and implementation sequence

Required stack: Python 3.11/`uv`, FastAPI/Pydantic/Uvicorn, PostgreSQL/psycopg,
`langchain-core`, LangGraph/PostgreSQL checkpointer, TypeScript/esbuild with
Python-served HTML/CSS/SVG, and OpenTelemetry-to-self-hosted-Langfuse. Use CustomerOps'
shared dependency ranges and a separately qualified lockfile. NumPy and optional
offline scikit-learn are domain-specific additions. Full selections, infrastructure,
isolation and frontend conventions are in `REALTIME_STACK_AND_UI_SPEC.md`, section 1.

```text
src\subsea_copilot\
  config.py                    # provider, pack and runtime limits
  contracts.py                 # data, role, scope and result models
  ingest.py                    # mappings, normalization, quarantine
  diagnostics.py               # quality, statistics and event eligibility
  localization.py              # candidate fit and ambiguity
  ontology.py                  # typed pack loading and procedure versioning
  store.py                     # evidence and business transactions
  replay.py                    # server-owned simulation clock and arrivals
  monitoring.py                # windows, revisions and episode transitions
  telemetry.py                 # OTel generation/tool/check/session metadata
  llm\copilot_cli.py            # bounded inference-only transport
  runtime\registry.py           # role/tool/edge contracts
  runtime\gateway.py            # scoped read-only tools
  runtime\agent.py              # shared LangGraph specialist loop
  runtime\workflow.py           # plans, children, leases and finalization
  validation.py                # claims and result acceptance
  api.py
  cli.py
prompts\quality.md
prompts\diagnosis.md
prompts\response.md
packs\
fixtures\synthetic\
tests\
eval\
web\index.html
web\ts\console.ts
web\styles.css
scripts\build-console.cjs
package.json
tsconfig.json
docker-compose.yml
docker-compose.langfuse.yml
```

Keep responsibilities small; do not clone CustomerOps' full case/email/recovery system.

| Planned endpoint | Contract |
|---|---|
| `GET /api/sites/{site_id}/snapshots/{snapshot_id}` | Canonical snapshot/coverage metadata authorized by the local session context. |
| `GET /api/incidents/{incident_id}/evidence` | Bounded diagnostic findings and original schematic data. |
| `POST /api/incidents/{incident_id}/questions` | Validated question, explicit mode and idempotency key; server binds site/snapshot and queues one response task. |
| `GET /api/tasks/{task_id}` | Task tree, real progress, status, accepted answer or explicit error. |
| `GET /api/tasks/{task_id}/trace` | Local operator-only diagnostic metadata; content capture off by default. |
| Replay/window/SSE endpoints | Scoped controls, current projection, immutable window evidence and resumable event stream; see real-time specification, section 5. |

Server binding is `127.0.0.1`. Monitoring and agent work use separate workers;
an HTTP request must not hold a database transaction during inference. CLI ingestion
accepts named in-scope fixture sources, not model-supplied filesystem paths.
Local session/role checks, CSRF and database isolation are required MVP work.
Customer SSO and production identity/security qualification remain pilot requirements.

LangChain exposes the model/tool interface; LangGraph routes and checkpoints tasks;
Langfuse displays actual attempt/generation/tool/guardrail traces through native OTLP.
It does not schedule agents or determine accepted answers. Verify stored traces and
show explicit observability degradation if export fails. Detailed capture/identity/
session rules and original console interactions are in the real-time specification.

### Build order and milestone completion

This refines the existing eight-hour target. It is a timebox for the minimal demo,
not a promise to build production orchestration in eight hours.

| Milestone | Effort | Implement / finish criterion |
|---|---|---|
| T0 - Proxy and contracts | 0.5 h | Freeze roles and shared stack; independent PostgreSQL/Langfuse bootstrap ownership; one bounded synthetic proxy probe with identity/status. No auth/quota retries. |
| T1 - Evidence pipeline | 1.25 h | S1-S6, normalization/conflicts, separate labels; server replay clock/arrival semantics and immutable 60-second/5-second windows; ingestion/replay tests. |
| T2 - Diagnostics and localization | 1.5 h | Continuous statistical/evidence gates/fit, coverage loss, late revisions and episode deduplication; S1/S2/common-mode/poor-coverage/crossing tests. |
| T3 - Shared runtime and three agents | 1.25 h | CLI/gateway/graph, PostgreSQL checkpoints and persisted children; material-incident queue, pinned basis, coalescing and real Langfuse trace linkage; failure/replay tests. |
| T4 - Operator UI/API | 1 h | TypeScript/esbuild console; sliding charts/map, play/pause/step/speed, sensor/evidence/task drill-down, SSE and truthful mode/freshness/uncertainty; three questions. |
| T5 - Qualification | 1.5 h | Frozen/live cohorts and checker regressions; PostgreSQL RLS/checkpoint, stream timing/reconnect, stalled proxy, actual Langfuse visibility; Python and frontend quality gates. |
| T6 - Package/rehearsal | 1 h | Clean-clone commands, verified GitHub URL, updated brief/report and timed multi-agent demo. |

Full private CLI-progress streaming, HA/distributed workers, production SSO,
advanced ML, arbitrary seek/window-size experimentation and advisory wording review
are outside the MVP timebox. Public monitoring/task-event SSE is required. Never cut
scope checks, missing-data handling, actual live-agent evidence or uncertainty to
make the schedule appear successful. If T3 exceeds the estimate, report the remaining
work rather than calling deterministic specialists an implemented multi-agent system.
The expanded requirements increase schedule risk; eight hours is a target timebox,
not a verified delivery estimate. Apply the additional milestone gates in the
real-time specification rather than silently omitting stack/UI/observability work.

## 10. Qualification and proof that the agents really work

Unit/contract tests:
- Normalization, conflicts, timestamps, validity and physically usable anomalies.
- Detector fit isolation from test labels and incident data; constant-baseline behavior.
- Spatial/temporal/failure-domain gates, methane lag and common-mode outages.
- Location fit, candidate units, incompatible range/multiple segments and missing inputs.
- CLI invocation/isolation/zero direct tools, JSON envelopes, inner final schema,
  stream bounds, timeout/cancellation and sanitized errors.
- Required tool receipts, cross-site evidence, unsupported claims and valid equivalents.
- Child creation idempotency, failed/abstained child, snapshot mismatch, stale-owner
  finalization and budgets unchanged after resumption.
- Event-time boundaries/warm-up, all-data loss, late revisions, speed equivalence,
  replay generation isolation and overlapping-window deduplication.
- Real PostgreSQL non-superuser RLS/tool-read-only/checkpoint scope; SSE reconnect
  and unauthorized controls; slow proxy independence and old-result labels.
- Actual Langfuse trace tree, unavailable-export warning, bounded redaction and
  requested-versus-observed model metadata.

Integration tests use an explicitly fake/scripted transport that emits real tool
requests; they validate workflow behavior but are **not live-model evidence**.

Live qualification uses the actual Copilot-backed adapter:
- Freeze leak, scattered-fault and insufficient-evidence snapshots.
- Ask each of the three primary questions three times on each snapshot: 27 answers.
- Include at least one fresh two-child investigation for each snapshot; subsequent
  compatible summaries can reuse its accepted specialist results. Report fresh versus
  reused latency/calls separately, rather than implying 27 fresh investigations.
- Record the role/task tree, model calls, tools, accepted claims, failures, latency,
  requested/observed model identities and usage per root question.
- A composite question must create separately scoped quality and diagnosis children;
  health-only and saved-summary questions must not run unnecessary specialists.
- Zero accepted fabricated citations, confirmed-leak/control claims or unsupported
  locations on mandatory safety fixtures.
- Compare single-agent and multi-agent flows on a small matched subset with the same
  inputs, permitted evidence and validators. Report accepted-correct, unsupported-
  accepted, legitimate abstention, false rejection, time and proxy usage separately.

Run deterministic held-out event/localization qualification independently of the LLM
cohort, following `..\PLAN.md`, section 8. A model summary cannot compensate for poor
diagnostic accuracy; perfect diagnostic fixtures do not prove LLM answer reliability.
Optional Isolation Forest and reviewer experiments are reported separately and can
remain unexecuted without pretending they were measured.

Planned commands, only valid after the package/CLI is implemented:

```powershell
uv sync --locked
npm ci
npm run build
npm run typecheck
# Bootstrap isolated local services/secrets and run migrations per the future README.
uv run subsea generate --seed 2026
uv run subsea ingest --fixture-set interview
uv run subsea provider-check --mode live
uv run subsea serve --host 127.0.0.1 --port 8086
# In separate terminals: use the implemented monitor/agent worker entry points.
uv run subsea evaluate --suite qualification --mode live
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

Provider check is one explicit synthetic invocation, not an automatic recurring probe.
Do not run a live suite when auth/quota is unavailable. GitHub publication and email
submission remain later tasks; this planning work does not perform them.

## 11. Done criteria and remaining deployment questions

The implementation is done when evidence receipts demonstrate three genuine
Copilot-backed agents, the measurement/authority boundaries above, defective data,
conditional localization, all three questions, hard-gate tests, an accessible repo
and a clean reproducible run. This also requires the CustomerOps-aligned PostgreSQL/
TypeScript stack, continuous sliding-window monitoring, interactive console and
actual Langfuse trace visibility; a static screenshot or compiled bundle is not proof.

Before a real customer pilot, resolve instrument calibration and propagation,
verified event labels, shared-failure metadata, historian integration, model-data
hosting approval, account entitlements/usage policy, production identity/isolation,
retention and operational escalation ownership. CLI authentication and local startup
do not answer any of those questions.
