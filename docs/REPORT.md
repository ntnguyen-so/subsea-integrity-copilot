# Engineering report: Subsea Integrity Copilot

## Decision and discovery

**Proposed:** a four-week read-only shadow pilot for fictional NorthSea Integrity
Operations, after data/security approval. The budget owner wants lower triage
effort without new safety liability. The instrumentation lead needs reproducible
evidence, credible sensor independence and honest localization uncertainty.
The unsigned alternative is their existing dashboard plus manual investigation.

The thesis motivates marine quality/provenance and interpretable anomaly analysis;
defense slide 47 motivates distributed sensing. Neither validates this demo's leak
localization. CustomerOps informs scoped authority, durable handoffs, exact
derivations and honest counters. AITOMATIC's public console informs the original
interactive visual design; it is not a reproduced DanaOS product or integration.
Source/JD mapping and milestone acceptance criteria remain in `PLAN.md` and
`TECHNICAL_IMPLEMENTATION_PLAN.md`.

## Implemented architecture

```text
Arrival-sorted synthetic source -> incremental canonical buffer
  -> 60s window / 5s hop / 5s lateness -> numerical evidence ledger
  -> immutable PostgreSQL snapshot -> episode / coalesced bounded root
                                       |
                  response workplan -> quality -> diagnosis -> checked response
                                       |
              LangGraph PostgreSQL checkpoints + fenced task/receipt transactions
                                       |
                    SSE projection -> original TypeScript console

Independent monitor and inference threads; bounded async OTel -> local viewers.
```

**Implemented:** FastAPI/Pydantic, PostgreSQL 16 with forced tenant/site RLS,
read-only tool role, separate checkpoint role/schema, Argon2 login and signed scoped
cookies/CSRF. NumPy is the domain-specific addition to CustomerOps' core stack.
LangChain wraps the tool-disabled Copilot CLI; LangGraph nodes interrupt before
external I/O, so replaying a node does not repeat an unrecorded business side effect.

Quality, diagnosis and response have separate prompts, permissions, typed results
and persisted tasks. Diagnosis depends on accepted quality; synthesis depends on
compatible evidence. Compatible reuse is explicitly linked, not a fabricated new
specialist inference. Child/link/parent-WAIT creation is one fenced transaction.
Reservations enforce role/root/generation budgets before execution. Durable global
auth/quota blocking cannot be evaded by changing replay generation or restarting.

**Implemented refinement after live failure:** the application performs each role's
mandatory scoped reads through the same audited gateway before model interpretation.
Replay-stable intake call IDs preserve reservations/receipts on restart. Models still
interpret evidence and submit separate checked role results; intake is honestly
attributed to the application. Exact schemas and final-turn protection avoid spending
the role budget on unbounded health pagination. No call ceiling or certainty gate was
relaxed.

Quality support is scoped to observed coverage and sensor-health facts, not proof
of a physical event or a particular hardware failure. This distinction prevents
a quality specialist from abstaining merely because the parent asks about a leak.
Actual specialist abstention still propagates explicitly; insufficient physical
evidence cannot carry categorical event or location claims.

A root has at most two children, ten model calls, eighteen tool calls and a
300-second elapsed bound. Automatic roots are episode-triggered/coalesced, not
scheduled every hop. Manual admission is scoped across generations. These are demo
resource guards, not an HA distributed scheduler.

## Evidence and numerical boundaries

**Synthetic assumptions:** three connected 800m segments; four paired stations per
segment, 24 nodes offset around the centerlines. Acoustic relative power, methane
in umol/L and temperature context are sampled at 1 Hz. Gateway mappings represent
shared failure domains, not independently verified subsea hardware.

Raw records retain provenance. Explicit timezone and unit adapters normalize known
formats; invalid timestamps/unknown units are not guessed. Missing values, spikes,
late arrivals and conflicting duplicates are retained/flagged. Conflicts cannot
silently become corroborating leak evidence. Historical windows use only evidence
released by their source clock; newer conflicts cannot rewrite an old chart.

Median/MAD against separate verified-normal history gives interpretable channel
scores. Persistent usable acoustic excursions, methane corroboration, neighborhood
support and independent failure domains determine the event hypothesis. Missingness
alone is not a physical event. A shared outage may be spatially coherent, so
"simultaneous alarms = leak" is deliberately rejected.

Eligible localization fits acoustic excess `A / (distance^2 + r0^2)` along each
centerline on a 25m grid. The compatible set is not a 95% confidence interval.
Crossing ambiguity and poor fit withhold unsupported precision. Geometry, mixing,
currents, attenuation and sensor calibration require field validation.

The LLM interprets tool evidence; it does not run continuous detection or invent
metres/probabilities. Accepted text is rendered from checked claim IDs, units,
scope and evidence membership. Private reasoning is not recorded. App/database/
viewer credentials are stripped from inference subprocess environments.

## Qualification and failures

**Measured, synthetic-only:** the frozen numerical report covers 120 mature windows
(20 seeds x six scenarios). Leak precision/recall are 1.0 in this controlled
population; S1 section/200m gates pass 20/20. Ideal-model chainage error is zero:
this reflects matched generation/fitting assumptions, not field accuracy.
Sensor-fault attribution precision/recall are **0.8/1.0**, retaining 100 false
positives. Model-mismatch stress has 18 locations/two abstentions and p95 error 25m.
Mature-window compute p95 is 0.476s; it is not end-to-end detection latency.

The first full PostgreSQL agent integration exposed missing graph bootstrap despite
passing isolated tests. Explicit checkpoint migration, fail-fast startup and real
database fresh/reopen/crash-handoff regressions address that gap. A later cohort
exposed question-inappropriate reuse omitting a location claim; acceptance gates
retain that failure rather than treating a merely well-formed answer as correct.

Current qualification receipts, browser evidence and remaining release gates are
reported in `RESULTS.md`. A single-agent comparison uses the same numerical evidence
and certainty checker but a CLI-only bounded authority policy. Compare actual
fresh/reused calls and latency, not hypothetical "swarm" performance.

Langfuse ingestion must show stored agent/generation/tool/guardrail observations.
Exporter HTTP success alone is insufficient. Bounded batching prevents a hung
viewer from stalling source windows; queue loss/flush failure is visible health.
Auth/quota failure preserves monitoring and returns explicit unavailable status.

## Commercial and meeting contract

**Proposed:** week 1 connector/schema/security review; week 2 shadow replay and
expert adjudication; week 3 operator workflow; week 4 joint gate review.
Measure reviewed false alarms, supported sensitivity where labels exist, coverage,
latency and median triage effort. Stop or revise when acceptance is not met.

Illustrative capacity value: `120 alerts/month x 0.25h x USD100/h x 12 = USD36,000/year`.
This is not verified savings or a vendor quote. Pilot scope/pricing needs approval;
inspection avoidance must not be sold as guaranteed cash savings.

60-minute choreography: 5m problem/unsigned objections; 10m S1/S2/S5 live console
and one raw defect; 30m numerical derivation, role authority, PostgreSQL recovery,
checked answers and real trace; 10m bounded pilot economics/risk; 5m out-of-role
questions about FDE ownership, deployment constraints and customer adoption.

**Not implemented/supported:** live historian ingestion, production multi-user
identity, certified leak protection, plant control, DanaOS integration, local-only
inference, field reliability or validated ROI. Reviewer access to this private
repository and email submission 24h before the interview remain the owner's actions.
