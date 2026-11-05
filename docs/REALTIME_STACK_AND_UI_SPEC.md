# CustomerOps stack, real-time monitoring and interactive console

Status: implemented design specification; see `RESULTS.md` for qualification evidence.
This document supersedes the earlier SQLite and minimally specified browser/replay choices.
Use it with `TECHNICAL_IMPLEMENTATION_PLAN.md` for the agent contracts and proxy.

## 1. Required technology stack

Use the same application stack and engineering conventions as the inspected CustomerOps
checkout. Share technologies and patterns, not its database, secrets, private records
or running services. The subsea repository must start independently.

| Layer | Required selection | Inspected CustomerOps evidence |
|---|---|---|
| Language and packaging | Python `>=3.11,<3.12`; `uv`, `uv_build`, src-layout package and CLI entry point. | `pyproject.toml:1-47` |
| API/server | FastAPI, Pydantic, Uvicorn and `tzdata`. | `pyproject.toml:7-19`; `src\custops\web\api.py` |
| Application database | PostgreSQL 16, `psycopg[binary,pool]`, migrations and transaction-scoped tenant context. | `docker-compose.yml`; `src\custops\store\db.py:307-367` |
| Isolation and roles | Forced PostgreSQL RLS, separate application/tool access, server-side role checks, session/CSRF protections; Argon2 password hashing. | `docs\architecture.md`; `pyproject.toml:8`; `src\custops\store\upgrade_0014.py:428`; `src\custops\web\security.py` |
| LangChain | Explicit `langchain-core` dependency for `BaseChatModel`, messages and tool schemas. | `src\custops\llm\copilot_cli.py:30-37,113-160`; no umbrella `langchain` package is required by the observed code. |
| LangGraph | Shared specialist graphs and `langgraph-checkpoint-postgres`; `PostgresSaver`. | `pyproject.toml:10-11`; `src\custops\runtime\checkpointer.py:9-19` |
| Live LLM transport | Authenticated, tool-disabled GitHub Copilot CLI adapter. | `src\custops\llm\copilot_cli.py:237-354` |
| Browser application | Python-served HTML/CSS/SVG with strict TypeScript DOM modules; esbuild bundling to a served asset. No React, Next.js or Streamlit. | `package.json`; `tsconfig.json`; `scripts\build-workbench.cjs`; `src\custops\web\ts\workbench.ts` |
| Trace instrumentation | OpenTelemetry SDK and OTLP/HTTP exporter; bounded/redacted capture. | `pyproject.toml:12-13`; `src\custops\telemetry.py:476-574` |
| LLM observability | Self-hosted Langfuse through native OTLP; no Langfuse SDK required for the inspected integration. | `docs\langfuse.md`; `src\custops\telemetry.py:447-463,532-574` |
| Supporting infrastructure | Docker Compose; application PostgreSQL and Jaeger; independent Langfuse web/worker, PostgreSQL, ClickHouse, Redis and MinIO with persistent named volumes. | `docker-compose.yml`; `docker-compose.langfuse.yml`; `docs\langfuse.md` |
| Python checks | pytest, Hypothesis, pytest-socket, httpx, Ruff, mypy and pip-audit. | `pyproject.toml:29-38,49-87` |
| Frontend checks | `npm run build`, `npm run typecheck`; ES2020 target, strict/no-implicit-any/no-emit type checking. | `package.json:5-12`; `tsconfig.json` |

NumPy for subsea numerical methods is a **domain-specific addition**, not an existing
CustomerOps runtime dependency. Optional scikit-learn is an offline ML comparison
extra. No Kafka, TimescaleDB, WebSocket framework or additional frontend framework is
needed for the initial stream.

Match the declared CustomerOps dependency ranges where shared and produce a tested
lockfile during implementation. Add `langchain-core` explicitly because this project
imports it directly, even though CustomerOps obtains it through its dependency graph.
Do not copy the CustomerOps lockfile and claim the subsea dependency set is qualified.

### Local ownership and startup

Use separate compose project names, databases, volumes, runtime directories and
Langfuse project credentials. Ports are configurable; illustrative non-conflicting
defaults are app `8086`, application PostgreSQL `15433`, Langfuse `3001`, media `9091`
and Jaeger viewer `16687`, all published on `127.0.0.1`. Verify actual availability
before starting anything; do not stop or reconfigure CustomerOps services.

Bootstrap secrets outside the repository with user-only access, following CustomerOps'
mechanism. Do not copy its credential file or hard-code a demo password. Keep keys
out of telemetry, API health, screenshots and public fixtures.

The minimal shared-stack implementation includes RLS and server-side role checks,
not merely a browser-selected site ID. Test with the real non-superuser application
role; a passing test under PostgreSQL's superuser does not validate isolation.
Production SSO, HA, operational certification and customer security approval remain
outside the interview demo.

## 2. Continuous monitoring is separate from agent execution

```text
Replay clock/source adapter
    -> observed-time + arrival-time batches
    -> normalize/validate/persist canonical observations
    -> event-time window scheduler
    -> quality + statistical anomaly + event/localization computations
    -> immutable window result / monitoring episode / durable UI events
           |                                    |
           |                                    -> SSE -> TypeScript console
           -> material incident trigger -> persisted three-agent workflow
                                            -> LangChain/Copilot + LangGraph
                                            -> checked answer + Langfuse traces
```

The monitoring worker owns the clock and window computations. A separately scheduled
agent worker owns model subprocesses and specialist tasks. Both can use the same
PostgreSQL store with short transactions and separate connections.
Never execute Copilot inference inside a window callback, hold a database transaction
across inference, or rely on the browser remaining open to advance the replay.

Initially use one monitor worker and one serial agent worker. Persistent work queues
are PostgreSQL task/event records, not in-memory-only browser state. A worker lease
prevents two monitor processes from advancing the same replay generation.
This is bounded local concurrency, not a claim of distributed high availability.

## 3. Clock and sliding-window semantics

### Initial configuration

| Parameter | Demo default | Meaning |
|---|---|---|
| Sensor sampling | 1 simulated second | 24 nodes, channel capabilities declared in metadata. |
| Window width | 60 simulated seconds | Time interval used for current diagnostics. |
| Hop | 5 simulated seconds | Recompute as the window slides. |
| Allowed lateness | 5 simulated seconds | Delay before calling a window complete under the source contract. |
| Replay speed | `1x`, with `2x`, `5x`, `10x` controls | Simulated seconds per wall-clock second, not sensor sampling changes. |
| Active lateness/revision horizon | 120 simulated seconds | Bounded buffer for revising recent windows; older arrivals remain recorded. |
| Warm-up | First complete 60-second window plus lateness | Incomplete history is labeled `WARMING_UP`, not "pipeline normal." |

Treat these as versioned demo parameters to qualify, not actual instrument requirements.
`WindowSnapshot` references its immutable `EvidenceSnapshot`; its ID/revision is the
existing agent scope's snapshot identity, not a second independently selectable scope.
Maintain `observed_at`, `received_at`, simulated source clock, operational clock and
browser render time separately. All diagnostic timestamps use timezone-aware UTC.

Replay emits only records whose simulated arrival time is reached. A known baseline
may come from explicitly provided pre-event verified-normal data; detectors and agents
cannot read unreleased replay values, scenario labels or future leak positions.

For replay source clock `C`, process completed hop endpoints `E <= C - lateness`.
For each `E`, the window is `[E - width, E)`: left included, right excluded. Enumerate
every eligible hop even at accelerated speeds; UI render coalescing must not skip
server-side computations.

The watermark advances with the declared replay clock, **not only the newest sensor
reading**. Otherwise an all-sensor outage would freeze time and conceal missingness.
For a real adapter, specify a bounded source heartbeat/operational-clock watermark
contract separately; do not assume the simulator's trusted clock exists in production.

Keep late samples in canonical storage. Revise affected completed windows only when
their endpoint is within 120 simulated seconds of the current watermark. Read their
full 60-second input interval from canonical storage; retention must include that
additional history. Each revision preserves lineage.
It cannot mutate a previous snapshot, silently change an accepted answer, or enter
an already running agent's pinned evidence. Out-of-horizon arrivals are visible as
late evidence outside the current correction horizon.

### Replay controls

- **Play/pause:** controls ingestion/source clock only. Pausing does not pretend to
  cancel already running LLM work.
- **Step:** while paused, advance one 5-second hop and ingest all arrivals up to the
  new source clock.
- **Speed:** preserve clock continuity by rebasing the monotonic wall-clock anchor.
  Do not multiply observation timestamps or silently drop samples.
- **Scenario selection/restart:** create a new `replay_generation_id`. Preserve prior
  generations, incidents, tasks and traces; never clear history to make a demo repeat.
- **Window width:** MVP uses the fixed qualified 60-second setting. Optional 30/120
  second views create a distinct parameter version and recompute; they cannot reuse
  results from the 60-second method as though they were identical.

Historical selection freezes the evidence inspector while the live monitor continues.
The screen must distinguish current monitoring from the selected historical window.
Arbitrary seek/scrubbing and window-size experimentation are optional after the core
play/pause/step/speed path works.

## 4. Event lifecycle, persistence and incident-triggered agents

Use window identity:
`(tenant_id, site_id, replay_generation_id, window_end, width, hop, parameter_version)`.
Window revisions add immutable input/evidence hashes and predecessor revision.
Observation replay/conflict rules remain those in the technical plan.

A **monitoring episode** groups related evidence over overlapping windows; it is
not a resolved operational incident. Correlate by site/generation, pipeline neighborhood,
compatible hypothesis class and time continuity. Do not count the same observations
in three overlapping windows as three independent confirmations.

Proposed hysteresis: require 15 seconds of raw event-time qualifying physical evidence
before opening a persistent suspected-leak episode; mark it `QUIET` only after 30
seconds without qualified evidence **while usable coverage remains sufficient**.
Exact durations are tuned on development data and frozen before qualification.

Episode states include `CANDIDATE`, `ACTIVE`, `QUIET`, `COVERAGE_LOST` and
`SUPERSEDED_BY_REVISION`. All-data loss produces `COVERAGE_LOST`, never evidence
of recovery or a safe pipeline. Operational resolution remains an authorized human
decision, separate from computed episode state.

Each window updates fast diagnostics and the console without an LLM. Trigger a
three-agent investigation for:
- A newly opened actionable episode.
- A material change in hypothesis eligibility, usable coverage or compatible pipeline
  section; qualify displacement/change rules in the pack.
- An explicit operator question requiring new evidence.

Do not launch three agents every 5 seconds. Permit one in-flight root investigation
per episode; retain a bounded pending material-update marker while it runs. Pin the
root's `basis_window_id` and revision at scheduling time. When it finishes, show its
actual basis time even if the stream has moved.

Unchanged windows do not require new LLM analysis. Reuse an answer only for its declared
evidence basis; exact snapshot-scoped caching cannot silently turn an old answer into
a current one. Display "analysis as of ..." and "newer monitoring evidence available."
If a material change is pending, schedule at most the latest eligible revision after
completion, under the existing episode budget. Record coalescing and suppressed work.

Initial automatic dispatch bounds: at most three root investigations per episode,
six per replay generation and one new automatic root per 60 wall-clock seconds.
Keep at most 16 queued roots and one latest pending marker per episode. Persist these
counters across worker/browser restarts; exhaustion is visibly `budget_blocked`,
and queue overflow is `queue_full`, while numerical monitoring continues.
Manual admission permits three new roots per operator per wall-clock minute.
All automatic/manual calls share a 100-model-call ceiling per replay generation,
checked before invocation in addition to each root's existing budget. Idempotent
question retries do not create new roots. Qualification uses a separately declared run allowance,
not automatic incident dispatch disguised as free background work.

Accelerated replay can outpace hosted inference. This is expected: the UI shows current
numerical monitoring and older/pending agent analysis separately, not fake agent
completion synchronized to the replay clock. Quota/auth failure leaves fast monitoring
running with a conspicuous unavailable-agent status.

## 5. Browser updates, data contracts and reconnects

Use FastAPI/Starlette `StreamingResponse` for server-sent events and browser `EventSource`.
No extra SSE library is required. Replay commands use authenticated POST requests with
the same role/CSRF discipline as other writes. Observation streams are read-only.

Publish durable event rows in the same PostgreSQL transaction as the corresponding
window/task state, then stream committed rows. Optional notifications can wake readers;
the database remains the source of truth. Do not keep an open SQL transaction for the
lifetime of a browser connection.

| Contract | Required fields |
|---|---|
| `ReplaySession` | Tenant/site/generation, source identity, seed, state, clock anchors, speed, method/pack versions. |
| `WindowSnapshot` | Window identity, bounds, revision/hash, watermark, warm-up/coverage, diagnostics, optional location and creation time. |
| `MonitoringEpisode` | ID, correlation scope, state, basis/current window, material revision and pending agent marker. |
| `ConsoleEvent` | Ordered event ID, type, tenant/site/generation, simulation and operational timestamps, window/task/run references, bounded payload. |
| `LiveProjection` | Latest window, selected historical basis, episode summaries, replay state, agent availability and update lag. |

Event types: `replay.state`, `window.completed`, `window.revised`, `episode.changed`,
`task.started`, `tool.completed`, `answer.checked`, `task.finished`, `health.changed`.
The rendered event feed is not private reasoning and cannot invent completed checks.

SSE reconnection uses `Last-Event-ID` or an explicit last-seen cursor, validates
tenant/site/generation, and deduplicates events in the browser. If a retained cursor
is unavailable, send `resync_required` and fetch a coherent projection; do not silently
lose the missing interval. Show disconnected/reconnecting/stale states explicitly.
Use bounded browser histories and server event retention with documented replay limits.

Planned endpoints:
- `POST /api/replays`: create a scoped generation from a named synthetic source.
- `POST /api/replays/{id}/control`: play, pause, step or speed with idempotency key.
- `GET /api/replays/{id}/projection`: coherent current view and cursor.
- `GET /api/replays/{id}/events`: authorized SSE feed.
- `GET /api/windows/{id}`: immutable window/revision and scoped evidence.
- Existing incident question, task and trace endpoints from the technical plan.

## 6. AITOMATIC console study and UI adaptation

The public home page's embedded operator-console visual was inspected in the browser.
Semiconductor, Building and Grid tabs were exercised; the rendered console changed
agent, deployment context, knowledge objects, event feed and governance panel.
The public HTML, CSS and console script were also reviewed.

Public references, inspected 2026-11-05:
- https://www.aitomatic.com/
- https://www.aitomatic.com/platform
- https://www.aitomatic.com/assets/js/console.js?v=50029c2d29
- https://www.aitomatic.com/assets/css/site.css?v=dc80b4de0c

The script defines domain fixtures and timed stages: attach, read, reason, propose,
verify, gate and commit. It rotates domains, scrolls the feed, highlights knowledge
objects and animates counters/token paths. Its read counts, confidence, quorum and
token usage are scripted presentation values. This is **not** proof of a public live
backend or the complete private DanaOS application's behavior.

### What to mimic and what to change

| Observed pattern | Subsea adaptation |
|---|---|
| Near-black console, warm amber accents, thin separators, compact navigation rail and monospace metadata. | Original industrial console theme with high-contrast readable labels and responsive pane layout. |
| Domain tabs replace the console's operating context. | Explicit Live / Evidence / Agents / Audit tabs; scenario/site controls never rotate automatically. |
| Knowledge objects carry entity/method/rule/policy type colors. | Pipeline/sensor entities, statistical methods, evidence rules and scope policy chips backed by the typed pack. |
| Timestamped feed and staged governance panel. | Persisted monitoring/task/tool/validation events; execution stages advance only on receipts. |
| Highlighted objects and token trail between panes. | Clicking evidence highlights its source sensors/window; optional motion illustrates an actual recorded transition, not a made-up governed write. |
| Bottom counters and budget track. | Actual usable observers/failure domains, current window bounds, queue/latency, model-call budget and provider usage when known. |
| Operator gate / approved-applied display. | Read-only recommendation and validation state. No pretend approval, shutdown or actuation. |
| Reduced-motion logic in the script. | Respect reduced motion; status and selection remain clear without animation. |

Create original HTML, TypeScript, styles, SVG topology and icons. Do not copy proprietary
website code, logos, third-party art or an entire branded screen. Label the application
Subsea Integrity Copilot, an interview demo; do not imply it is DanaOS.
Use locally available system fonts initially, or separately licensed bundled fonts.

### Console layout

```text
Header: site | SIMULATED STREAM | READ ONLY | replay clock | connection | agent status
Navigation rail: Live / Evidence / Agents / Audit
Context toolbar: scenario | play/pause | step | speed | window bounds | warm-up/lag

Live workspace:
  asset/episode list | original pipeline + sensors map | selected sensor/episode details
  sliding channel charts and shaded current window    | agent result / ask panel

Footer:
  usable coverage | independent domains | window/episode state | queue | budget/usage
```

At desktop sizes, prioritize the pipeline map and charts rather than reproducing a
small marketing-console illustration. At narrower widths, use labeled tabs/drawers
without hiding material uncertainty or the current/selected-window distinction.

### Required interactions

1. Play/pause/step/speed visibly advance the server-owned clock and window.
2. Select a scenario explicitly; it starts a new generation with visible history.
3. Click or keyboard-select a sensor to pin its details, chart channels and raw/canonical
   evidence; hover is an additional tooltip, not the only access path.
4. Select an episode to highlight compatible pipeline sections, supporting and
   contradicting sensors and the exact evidence basis.
5. Click an evidence/criteria chip to open a scoped detail panel and highlight its
   related topology. Selection persists across stream updates.
6. Expand actual quality/diagnosis/response tasks to inspect public tool summaries,
   validation outcomes, limitations and same-session Langfuse links.
7. Filter/pause event-feed auto-scroll while inspecting history; new-event count remains
   visible. Resuming scroll does not trigger new agent work.
8. Ask the three primary questions against an explicitly pinned window; display the
   accepted answer's source time and live-versus-scripted mode.

Sensor health and event evidence use separate visual encodings. Missing/conflicted
channels use a labeled hollow/hatched state; suspect sensor faults and coherent leak
support must not both be rendered as an undifferentiated red dot.
Draw gaps in charts as gaps, not zeros or an interpolated healthy line.
Show multiple candidate segments when localization is ambiguous.

Do not inherit the marketing UI's "Your boundary", "on-prem", confidence `0.94`,
quorum `2/3`, applied status or invented knowledge growth. Show:
**synthetic source; local application; Copilot proxy inference; read-only authority**.
When usage is unavailable, render `not reported`, not a decorative token animation.

Accessibility: keyboard focus, real buttons/tabs, `aria-selected`, labeled SVG objects,
non-color status text, accessible chart/table alternatives and reduced motion.
Use restrained `aria-live` announcements for material incidents, not every sample.

## 7. LangChain, LangGraph and Langfuse ownership

LangChain owns model/message/tool interfaces. LangGraph routes and checkpoints agent
execution. PostgreSQL business services own evidence, tasks, authorization and outcome
acceptance. Langfuse observes and supports evaluation; it is not the task scheduler,
permission gateway or source of truth for incident status.

Follow CustomerOps' native OpenTelemetry-to-Langfuse integration rather than adding
a second callback path that double-counts generations. Self-host the viewer locally;
read ingestion credentials from environment only. The configured endpoint must be
loopback; no hosted trace export is enabled automatically.

Trace structure:
- Monitoring spans: source ingest, window compute, event assessment and fit; no fake
  `generation` when no LLM runs.
- One trace per agent attempt: `agent` root, `generation` per actual Copilot call,
  `tool` per gateway dispatch and `guardrail` per acceptance check.
- Parent/child and resumed attempts: explicit links and task IDs, not invented
  parent spans kept open across long waits.
- Session grouping: hashed tenant/site/generation/episode identity; every nested
  observation inherits session scope. An operator question links to its episode
  while retaining a distinct root/task/run identity.

Record source window/revision, role/purpose, requested/observed model IDs, mode,
budgets, duration, usage availability, errors, validation rejection and repair.
Keep content capture off by default; synthetic-only bounded/redacted capture is an
explicit rehearsal setting. Do not trace private reasoning or credential values.

Separate diagnostics distinguish exporter disabled/misconfigured/unavailable, accepted
export and confirmed stored trace. Verify the actual Langfuse tree with model/tool/
guardrail observations; an HTTP export acknowledgement does not prove UI visibility.
Monitoring and accepted business results remain available if the viewer fails, with
an explicit observability health warning and persistent local audit.
Do not silently call a broken mandatory observability check a successful release.

Local prompt files are versioned and their hashes appear in traces. Offline evaluations
can be imported/reviewed in Langfuse, but model judge scores are advisory. Hosted
evaluators and remotely editable runtime prompts are not enabled in the MVP.

## 8. Milestone extensions and acceptance criteria

The existing eight-hour schedule remains an MVP timebox, not a guaranteed estimate.
Same-stack infrastructure, continuous monitoring and a fully interactive console
increase delivery risk. Keep the core requirements; defer arbitrary seek, custom window
sizes, cosmetic motion and advanced ML first. Do not relabel omitted features complete.

| Milestone | Additional required completion evidence |
|---|---|
| M0/T0 | Independent PostgreSQL/Langfuse ownership, pinned shared-stack dependencies, documented secrets/bootstrap and one bounded proxy probe. |
| M1/T1 | Replay generation, clock/arrival semantics, canonical ingest and 60-second/5-second window identities. |
| M2/T2 | Continuous diagnostics, all-data-loss coverage, late revisions and deduplicated episodes; no future-label/sample access. |
| M3/T3 | Material-incident triggering, one in-flight root per episode, coalescing, pinned basis and actual LangChain/LangGraph/PostgreSQL workflow; Langfuse trace linkage. |
| M4/T4 | TypeScript/esbuild console, real replay controls, sensor/episode/evidence drill-down, task tree, SSE reconnect and truthful current/historical status. |
| M5/T5 | Real PostgreSQL RLS tests, streaming/time/agent/trace checks, npm build/typecheck and existing Python quality gates. |
| M6/T6 | Clean independent startup, accessible GitHub run guide and timed live sliding-window demonstration. |

Required regression/qualification cases:
- `[start,end)` boundaries; partial warm-up; gaps; duplicate arrivals; late revision;
  all-sensor loss while the source clock continues.
- Identical event-time results at `1x` and `10x` when arrival semantics/parameters match.
- Pause/step/speed continuity and replay-generation isolation; no deletion/reset of
  historical evidence or budget counters.
- Overlapping windows do not inflate independent observer counts or create duplicate
  episodes/investigations.
- Slow/unavailable Copilot leaves the stream running; current versus old answer basis
  remains clear; material changes are coalesced without widening task scope.
- SSE disconnect/reconnect, cursor deduplication, scoped history and explicit resync.
- Unauthorized replay controls, wrong-tenant event feed/evidence and checkpoint scope.
- Real Langfuse generation/tool/guardrail tree, independent exporter-failure warning and
  no secrets/private reasoning in capture.
- Keyboard sensor selection, evidence drill-down, missing chart gaps and reduced motion.

Performance targets to measure: at `1x`, p95 completed-window computation below one
wall-clock second at the demo's 24-node load; current projection rendered within one
second of publication under normal loopback conditions. Report watermark delay,
window hop delay, compute, publication, browser lag and agent latency separately.
Do not call a 5-second hop plus 5-second lateness "instantaneous" detection, or claim
accelerated replay proves a real-world latency SLO.

Frontend checks are `npm ci`, `npm run build`, `npm run typecheck`. Python checks remain
pytest/Ruff/mypy, with PostgreSQL services required for RLS/checkpoint integration tests.
Verify interactive outcomes in the running UI after implementation, not merely that
the TypeScript bundle compiles. No services or application UI were built by this spec.
