# Engineering report: Subsea Integrity Copilot

## Evaluating the agent workflow itself

The [agent operations evaluation](AGENT_EVALUATION.md) defines a matched
six-scenario, three-question benchmark against an actual quality-aware fixed
retrieval/comparison/report workflow. It audits persisted role dependencies,
tool arguments/results, incident-time sources, grounded handoffs, scoped reuse,
critic/reflection phases, attestation, call accounting, budgets and idempotence.
Every planned case, failed attempt and raw receipt is retained. Structured
report correctness, operational correctness and end-to-end report latency are
separate measures; numerical warning latency and human review time are separate
clocks. This does not equate self-review with independently measured prose
accuracy or assume that agents are faster than a zero-LLM report template.

## Current implementation: pressure-alert investigation

The customer's detectors already identify unusual pressure readings. The demo
therefore models **investigation after alerts**, not replacement of those
detectors. A frozen median/MAD one-class model provides a lightweight, inspectable
stand-in: fit on verified-normal pre-roll, normalize pressure to bar, then score
both upward and downward excursions. Its center and scale are visible beside
the sensor chart. Neither fitting nor numerical diagnosis uses an LLM.

The historical three-segment pressure-v3 reference uses an upright Y: Trunk P1 below the junction,
Branch A P2 upper-left, Branch B P3 upper-right. Each segment is 800m, with
stations at 100/300/500/700m. Paired A/B instruments sit on opposite walls of an
assumed 0.6m pipe, for 24 instruments at 12 stations. Mixed bar/kPa/MPa, explicit UTC/local
timestamps, missing records, nulls, sentinels, late arrivals, duplicates, spikes
and isolated drift exercise normalization and data-quality investigation.
Source versioning prevents older acoustic or pressure-v2 generations from being
regenerated under the new deployment. Historical snapshots and receipts remain immutable.

The numerical investigation correlates time and **pipeline-network distance**,
not just map proximity. A suspected leak needs overlapping negative anomalies
for 15 seconds from at least three instruments, two stations and two failure
domains within 400m. A/B instruments at one station share a gateway and are not
independent corroboration. Same-station disagreement supports sensor review without
silently excluding all anomalous measurements. A leak and a separate fault can
coexist. Gaps and unsupported single drops do not establish a healthy pipeline.
Brief correlated transients and broad common-mode drops retain uncertainty:
valve/compressor changes and shared failures require operator-supplied context.

For localization, affected stations must be bracketed by unaffected pressure
stations on the same connected segment. Midpoints between affected and adjacent
unaffected stations define a **priority inspection interval**. Missing brackets,
disjoint regions or an interval wider than the configured maximum withhold it.
For S1 seed 2026, affected P1 stations at 300/500m and unaffected stations at
100/700m yield **200-600m**. The 400m display midpoint is not a predicted source.
This intentionally avoids a fabricated exact coordinate from a Gaussian signal.
The profile is illustrative, not a hydraulic simulator or negative-pressure-wave
time-of-arrival algorithm.

Three durable roles remain: Sensor Quality, Event Diagnosis, Operator Response.
They interpret bounded, read-only evidence and competing explanations; the
application owns intake, arithmetic, claim references and factual rendering.
An independent monitor preserves the existing 60s windows, 5s hops, lateness,
revision history, source-clock acceleration and provider-outage isolation.
The console shows pressure histories, frozen normal bands, anomaly markers,
quality issues and interval boundaries. Physical wall offsets are preserved in the
pack and exaggerated for selection/readability. The comparison panel uses common
time and pressure axes, including representative faults across all three segments.

### Brief-to-demo customer walkthrough

Use **S7, seed 2026**, for the canonical buyer walkthrough. The brief's selected
dashboard crops share source +50 to +110 seconds and the same measurements/alerts.
Those are evidence-window bounds, not established physical onset or report-delivery
times. The selected recording reports a P5 700–900 m inspection priority; do not
transfer that interval to another snapshot. The later +120 checkpoint in
`RESULTS.md` reports 600–1000 m. Interval eligibility and width are snapshot-specific.
The older S1/S2 exporter and three-segment examples below are historical reference
derivations, not the current brief's capture provenance.

| Brief question | What to demonstrate | Acceptance evidence |
|---|---|---|
| Leak, instrument error or operating change? | In the selected S7 recording, review the P5 pressure-loss focus separately from P7 shared instrument effects and P2 operating/process review. | Open the exact-window measurements, failure domains, counterevidence and cited records. These are hypotheses, not confirmed physical causes. |
| Where and when should we investigate? | Show P5, the selected source window, affected/neighbor stations and the accepted interval or withholding reason. | Distinguish evidence window, observed change timing, unknown physical onset and wall-clock completion. No exact source prediction or dispatch authorization. |
| What remains for the engineer? | Inspect sources, test competing explanations, obtain missing operating/field evidence and approve the handoff. | A plausible operating change does not clear a concurrent leak; partial health review does not certify every instrument. |

### Adaptive, history-grounded investigation

The fictional corpus is authored before runtime integration and includes operating
logs, maintenance records, procedures, an expired incident analogy, conflicting
revisions, a draft and a future inspection report. No employer/customer data is
used. Each record has asset scope, authorship, availability, effective dates,
revision and approval status. Backend scenario tags construct separate synthetic
worlds; they are not returned to the model as diagnosis labels.

Documents are indexed with PostgreSQL full-text search under forced tenant/site
RLS. Each task pins a content-hashed immutable corpus version. `history.search`
filters incident-time visibility and topology-expanded asset scope (a segment
includes its sensors/gateways); `history.read` follows discovered
IDs; `history.compare` computes actual before/after pressure summaries for model-
selected sensors and periods. Raw observations are filtered by received time
before conflict normalization, preventing future arrivals from contaminating a
past comparison. SQL and numerical code, not embeddings or the LLM, own measurements.

Mandatory quality/event intake remains application-owned. After observing it,
the diagnosis model chooses search terms, documents, sensors, ranges and bounded
investigation intents. It can stop unresolved when evidence is absent. This is
adaptive evidence gathering, not access to arbitrary tools or unbounded reasoning.
The original history-loop qualification used four diagnosis turns including the
final result, two children, ten model calls, eighteen tool calls and 300 seconds.
These are historical qualification settings, not the current resource contract.
The current root elapsed deadline is 900 seconds; actual calls and elapsed times
must be read from each receipt rather than inferred from those older limits.
Compact serialization avoids duplicate schema input. A finite 48,000-character
prompt envelope replaces the earlier 32,000-character pressure-only envelope;
it accommodates retrieved evidence without increasing call budgets. Actual
provider serialization is checked in offline integration tests. Input capacity
is not a measured token bill; pilot costing must include prompt volume.

The final structured context must cite fully read current approved documents and
executed comparison call IDs. An operating-change explanation needs a contemporaneous
operation record and adequate measured changes across multiple segments; matching
maintenance context also needs current quality concerns. These checks establish
support for a plausible explanation, not causation. The physical-event ledger and
inspection interval are never overwritten by retrieved prose. S4 therefore retains
physical abstention while adding a plausible operating explanation. Response tasks
must preserve the diagnosis review exactly, including on abstention. S5 can
legitimately cite a telemetry work order as instrumentation context while its
physical cause remains unknown; the evaluation must not confuse that with a leak
clearance. Its accepted workflow still abstains and restores observation coverage.

The UI exposes executed investigation steps and sources, not hidden model
chain-of-thought. Retrieved text is advisory evidence, never authority to run
instructions, dispatch work or control an asset.

## Knowledge, collaboration and interpretation

### Product thesis: reusable expertise, timely warnings, checked investigation

Expert knowledge is difficult to elicit and translate into executable systems.
The proposed product captures reviewed procedures, asset/failure-domain metadata
and worked investigations so that engineers do not repeatedly reconstruct the
same reasoning from alarms. The intended benefit is to make scarce expertise
available to newcomers and across a larger network, not to replace accountable
integrity experts. The demo has fictional versioned records and criteria; expert
elicitation, approval/change management and measured onboarding benefit are
customer-pilot work, not implemented automatic knowledge acquisition.

Ten minutes for manual investigation is an unmeasured discovery assumption.
**Five minutes is an unmet planning aspiration, not a customer-agreed SLO.**
The current root elapsed deadline is **900 seconds**, not a response-time promise.
The latest frozen-code S7 rehearsal completed three fresh roots in
526.532/538.375/595.968 seconds (8.8–9.9 minutes), each after revision and review.
All exceeded five minutes; none proves a labor saving or future acceptance.
Queueing, report completion, retries and human handling must be recorded separately,
with late, rejected and failed work retained in the denominator. See the latest
rehearsal note in `RESULTS.md`; older 300-second cohorts retain their original scope.

Warnings have a different clock. The numerical loop publishes a possible-leak,
coverage, instrumentation or unresolved warning without waiting for any model.
The global UI warning follows the latest monitoring window even while an engineer
investigates an older pinned snapshot. Disconnection/staleness is explicit and
never becomes a no-leak indication. Source-onset-to-warning, actual browser
delivery, request-to-accepted-report and human acknowledgement must be measured
separately. A fast incorrect report does not meet the acceptance gate.

### Review of agent collaboration, criticism and reflection

The implemented collaboration is serial and dependency-controlled, not a debate
or a majority vote:

1. Sensor Quality reads coverage, conflicts, patterns and failure-domain metadata.
   Partial review is disclosed; it cannot declare a physical event.
2. Event Diagnosis consumes that accepted quality result, computed event and
   counterevidence, then selects incident-time history searches/reads/comparisons.
   Operating context may explain a pattern but cannot clear a leak or override
   numerical independence/location constraints.
3. Operator Response consumes the actual specialist evidence and reviewed
   document/comparison bodies, retains their limitations and produces the
   question-specific explanation.
4. The application critic checks scope, authority, required reads, claims,
   source status, linked dependencies and abstention. A rejection now gives the
   author its concrete bounded diagnostic, not just an error code. The graph
   permits one correction; a second rejection fails explicitly.

5. New `engineer-v2` response tasks invoke a separately prompted, tool-free
   grounding critic on the original claim objects, document bodies and computed
   comparisons. It reviews every answer, competing cause and follow-up question.
   Code requires exact paragraph coverage, valid per-paragraph references and
   literal source-quote anchors. A missing, malformed or uncertain review cannot
   approve a report.
6. Grounding rejection permits up to three author revisions, limited to interpretation.
   The reviewer supplies a source-bound, actionable correction checklist for each
   rejected unit, and the coordinator addresses all listed corrections together.
   Acceptance stops retries immediately. Any change
   to physical claims, outcome, history assessment, recommendations or limitations
   is rejected. A fresh critic must accept every revised paragraph; otherwise
   the whole report is withheld. Numerical warnings continue independently.
7. An application-owned review record binds the exact result and source-packet
   hashes. API/download validation repeats these checks. Distinct checkpoint
   threads preserve critic/revision phases; model receipts expose each phase.

This is independent context, **not an independent underlying model or expert**.
All roles can share model errors, and exact quotes do not prove entailment.
The semantic judgment remains probabilistic and requires human review.
Archived `engineer-v1` answers remain unchanged and labeled unreviewed.

A read-only adversarial reproduction confirmed the gap: an invented statement
about an inspection photograph and a pipe-wall crack passed the previous validator
when attached to the accepted OP-VALVE-001 citation. That source only describes a
valve setpoint command. The physical result was not changed and nothing was
persisted. `evidence\interpretation-grounding-audit.json` retains `passed:false`;
this failure must not be hidden behind passing schema or workflow tests.

`grounding.py`, `prompts\critic.md` and the response workflow implement the new
gate. The response's per-role model allowance is six only for `engineer-v2`;
PostgreSQL enforces this protocol-bound allowance and immutable protocol identity.
The original qualification used ten model calls, eighteen tools, two children and
300 seconds; the current root deadline is 900 seconds. A full revision can exhaust
the applicable receipt's resource allowances if specialist work was
expensive; failure is explicit, never a fallback to unchecked prose.
`scripts\qualify-grounding.py` replays authored adversarial paragraphs through the
same production critic prompt, context builder, graph and validator. It preserves
correct original citations while injecting unsupported claims. Original answers
and sources are never changed. Full-workflow and critic-only results remain
separate in `RESULTS.md`; neither is independent field validation.

The product acceptance goal is zero observed unsupported or unsafe assertions
in the agreed qualification set, with every failure retained. Also measure
missed/false warnings, interval containment/width, appropriate abstention,
failure recovery, completion/deadline rate and novice-versus-expert decision
quality. No zero-hallucination guarantee or production safety certification is
claimed.

### Current interpretation contract

The LLM is responsible for interpreting an engineer's question and explaining the
RCA context, not computing pressure thresholds or asserting a physical cause.
New `engineer-v2` responses contain a direct question-specific answer, competing
causes (possible/not established/not testable), supporting references and follow-up
verification questions. The planner sees the prior question and actual investigated
records, sensors and periods before choosing reuse versus a fresh specialist review.

Interpretation is a separate advisory channel, rendered before the checked
numerical ledger. Each paragraph must reference accepted claim IDs, current
reviewed documents or executed comparisons. Unread/stale/invented references and
interpretation from specialist roles are rejected. Numeric claims, inspection
intervals, physical abstention and read-only recommendations retain their existing
checks; the model cannot override them through a new structured verdict.

**Residual risk:** citation membership is not semantic entailment. The prose is
explicitly marked model-written and not independently verified RCA. It needs
engineer review; no automatic action consumes it. This is a deliberate language
interpretation feature, not a claim that arbitrary model wording is proven factual.
The immutable response-protocol pin keeps older evidence-only answers reproducible.

### Closing the alert-to-investigation workflow gaps

The buyer-facing gap was not another detector: the engineer still had to assemble
the answer, inspect raw JSON for historical evidence and manually copy a suggested
follow-up. The console could also fall back to another window's answer or a
specialist result when no matching operator response existed. Those behaviors
made a technically checked answer difficult to review and easy to misread.

`casefile.py` now derives a typed `investigation-v1` review packet from an accepted,
scoped `engineer-v2` operator response, including its grounding attestation.
Archived `engineer-v1` packets remain labeled unreviewed. The API revalidates the root and compatible
linked specialist results against the immutable snapshot and actual receipts.
It exposes a packet only for completed accepted operator responses; pending,
failed, specialist and pre-engineer-protocol exports return an explicit conflict. Legacy task
details remain readable without inventing a new interpretation.

The packet separates code-owned disposition, supported inspection interval,
checked numerical claims and limitations from model-written interpretation.
An interval requires an accepted location claim, not merely a location somewhere
in the snapshot. Fully read documents retain their actual text, revision,
incident-time authority and cited/rejected/read-but-not-cited status; comparison tables
show computed medians, usable counts and failure domains. Public executed checks
are receipts, not private reasoning. Task, generation, snapshot, input hash and
pack/baseline/parameter/history versions travel with the downloadable JSON.
The packet explicitly remains unapproved by an engineer and cannot dispatch
inspection, clear a leak or control equipment.

The UI puts this handoff ahead of collapsed execution debugging. Reference
buttons open readable evidence. Follow-up buttons draft against the original
window without submitting inference; the engineer explicitly submits the next
question. Default answers must match the selected window and be operator roots.
An explicitly opened historical answer carries a mismatch warning; stale
asynchronous detail requests cannot replace a newly selected window's answer.
Fresh call counts exclude earlier reused-specialist calls. Recorded elapsed time
includes queueing, and monetary cost is unknown.

The acceptance target is a reviewable investigation, not persuasive prose alone.
Browser journeys cover a supported S1 interval, S2 sensor/telemetry review and
S4/S5 physical abstention, source inspection, draft-only follow-ups, exact-window
selection and actual JSON download. An opt-in hosted browser journey asks an S4
question, reviews a source, submits a generated follow-up and downloads the new
root's handoff. The mature S4 fixture has no automatic roots and uses the normal
console tenant, authentication and rate limits; it is not an ingestion-speed test.
Current outcomes and retained evidence are recorded in `RESULTS.md`.

**Buyer gate:** this closes demonstrable workflow gaps, not proof of labor savings.
A customer-approved shadow pilot must compare review effort, evidence
completeness, inappropriate recommendations and total operating cost against both
manual work and a strong fixed workflow. Existing detector/historian/maintenance
connectors, human approval integration and field validation remain unimplemented.

### Context-sensitive inspection-priority evaluation

`inspection_evaluation.py` adds a separate research/evaluation path, not a bypass
of the production agent's physical authority. Sixteen authored synthetic cases
use the original 24-instrument Y topology, real normalization, frozen median/MAD
findings and `localization.locate`. Per-segment fits are **conditional candidates**:
they ask where each sustained pressure region would be bracketed if physical.
They do not change the global event verdict or establish multiple leaks.
Missing unaffected reference stations and an isolated disagreeing tap withhold
candidates before any model sees them.

The task is to rank unexplained areas ahead of areas with a verified matching
operating explanation. Every lower-priority area remains subject to investigation;
neither maintenance nor an operating log proves there is no leak. Cases exercise
execution versus paperwork state, parent-asset misfiling, supersession, quoted
history, an isolated calibration connection, conflicting accounts, unavailable
and unapproved sources, and unrelated bad samples. Dirty original units, clock
formats and missing values retain the existing ingestion path.

Both alternatives see identical candidate geometry and all incident-visible
records. The fixed context workflow checks approval, supersession, asset matches,
execution language and conservative counterevidence phrases. It does not merely
choose the largest anomaly or ignore history. Its four development cases and
twelve held-out cases are identified before hosted evaluation; data, numerical/
baseline code, model policy and evaluation script hashes are retained. Cases are
author-created and inspected; the `held_out` fixture label does not mean an
independently authored or developer-blind test. The model
does not receive expected decisions or the split. No prompt/baseline adjustment
is made in response to held-out outcomes.

Scoring separates exact first-priority sets, unjustified demotions, unnecessary
first-priority areas and failed responses. Model-selected IDs cannot invent a
coordinate; demotions must partition the candidates and cite current approved
matching records. Those checks establish provenance, **not semantic entailment**:
misreading a record is an evaluation error even if the citation passes.
Zero-candidate abstentions are explicitly code-owned, with zero inference calls.

This lab runs through the actual Copilot adapter but is not the three-role
durable workflow or sixteen new console replay scenarios. It isolates contextual
interpretation rather than confounding it with retrieval quality or additional
tool access. Held-out here means excluded from the four development cases, not
an independently authored customer trial. It does not benchmark graph ML,
hydraulic localization, human effort, field safety or production ROI. Detailed
outcomes and retained negative evidence are in `RESULTS.md`.
Three engineering questions exercise operating context, drift versus assumptions,
and inspection precision; they demonstrate functionality, not effort savings.

### Buyer review: why not graph ML or a fixed workflow?

Graph-based ML is a valid candidate for signal correlation when training and
validation data justify it. This small synthetic dataset does not justify a trained
GNN or establish graph-ML performance. The current numerical layer already uses
pipeline connectivity and independent failure domains.

The agent's proposed value is selecting and explaining additional evidence across
measurement, maintenance and operating systems. We test a broad fixed retrieval
workflow and a stronger quality-aware fixed workflow using the same visible corpus
and numerical checker. In the scripted four-case comparison, adaptive retrieval
matched 4/4 expected contextual outcomes, broad fixed retrieval 3/4, and the stronger
fixed workflow 4/4 with zero LLM calls. The stronger result is intentionally retained:
these cases do not prove an agent is necessary or more accurate.

As the budget owner, approve only a scoped shadow pilot, not production safety use.
Agree investigation-effort, supported-answer, reviewed-false-alarm, latency and
total-cost criteria against manual and stronger fixed baselines before collecting
results. Keep the cheaper workflow wherever it performs equally well. Stop if
additional agent value or approved data access cannot be demonstrated. Field leak
sensitivity still needs independent labels or validated tests; no savings or causal
diagnostic accuracy is inferred from this demo.

Review rounds cover the brief contract, source/artifact consistency, then the real
browser and hosted-model journey. The purchasing proposition is a reproducible
investigation rather than more alerts. Pilot comparison must measure engineer time
and reviewed false alarms against today's manual workflow; this demo establishes
neither customer savings nor field sensitivity.

Held-out pressure evidence covers 20 seeds x six scenarios. All 120 expected
mature-window conclusions matched; all 20 observable-leak intervals contained
the simulated source. Three false-positive fault suspicions remain visible.
S5 is an unobservable leak, not a successful detection, and is excluded from
observable-leak recall. Earlier pressure-only scripted qualification accepted 27/27 answers;
that establishes workflow/claim execution, not hosted inference. A separate
nine-answer pressure LIVE cohort passed using observed `gpt-6.1-sol`, with a
passing numerical-only single-agent comparison and verified stored trace tree.
These older cohorts do not qualify the adaptive history loop. See `RESULTS.md`
and explicitly pressure-labeled receipts for current evidence.

Production work still requires customer detector/feed adapters, real operating-context
integration, pressure/hydraulic calibration, independent labeled or validated
events and customer-defined acceptance gates. The system is read-only decision
support with human safety authority; hosted inference is not local-only.
Cost reduction and field reliability remain pilot questions, not measured ROI.

## Archived acoustic design and investigation history

**The remaining sections describe the previous acoustic/methane/temperature
implementation.** Its inverse-distance fitting, 27/27 LIVE cohort and historical
metrics do not qualify the current pressure version. They are retained for design
history, not as the active implementation specification.

## Decision and discovery

**Proposed:** a four-week read-only shadow pilot for fictional NorthSea Integrity
Operations, an offshore oil-and-gas prospect whose gas pipelines are modeled here,
after data/security approval. The budget owner wants lower triage
effort without new safety liability. The instrumentation lead needs reproducible
evidence, credible sensor independence and honest localization uncertainty.
The unsigned alternative is their existing dashboard plus manual investigation.
The proposed agent augments that workflow as a read-only evidence layer; it does
not require replacing the customer's digital data platform.

The commercial risk is asymmetric, not simply "too many alerts": false alarms can
mobilize offshore personnel, vessels or ROVs unnecessarily; missed releases can
cause environmental damage and liability. Oil-line spills add cleanup exposure,
but this gas-signature demo does not establish oil-spill detection. Serious
regulatory non-compliance can threaten licences; revocation is a possible legal
consequence, not the automatic result of every missed leak. Mobilization cost and
the prospect's exposure are discovery assumptions, not measured customer facts.

The thesis motivates marine quality/provenance and interpretable anomaly analysis;
defense slide 47 motivates distributed sensing. Neither validates this demo's leak
localization. CustomerOps informs scoped authority, durable handoffs, exact
derivations and honest counters. AITOMATIC's public console informs the original
interactive visual design; it is not a reproduced DanaOS product or integration.
Source/JD mapping and milestone acceptance criteria remain in `PLAN.md` and
`TECHNICAL_IMPLEMENTATION_PLAN.md`.

### Source grounding and boundaries

**Research:** thesis Paper C, "Synthesized Data Quality Requirements and Roadmap
for Improving Reusability of In-situ Marine Data," IEEE RE 2023, pp. 65-76
(thesis PDF viewer pages 162-164), identifies strict accuracy, currentness,
completeness and consistency needs for pipeline monitoring. It discusses business
loss from false alarms and environmental risk from delayed or missed detection,
including missing data and environmental/sensor confounders. It does not establish
the fictional prospect's inspection costs, validated localization or automatic
licence revocation. Defense slides 16 and 18-21 motivate source-aware quality
semantics and stakeholder-specific requirements; slide 47 motivates distributed
sensing. Neither an 85% target from other research use cases nor a research latency
example is adopted as a pipeline safety SLA. Edge AdapAD/Green Edge AI is not
claimed as implemented.

**Regulatory qualification:** an
[archived Norwegian Petroleum Act translation](https://s3.amazonaws.com/rgi-documents/be789afe11121decb40cf578900808634aed5aa2.pdf),
PDF pages 38-39, section 10-13 permits revocation for serious or repeated violations;
section 10-16 addresses temporary suspension. This supports a conditional risk
scenario, not legal advice or verified current applicability to the prospect.
The thesis and legal source are distinct.

**Public industry context:** [Falkor's product description](https://falkor.com/products/falkor)
positions industrial intelligence around connecting people, systems and workflows
and combining simulation, physics-based AI and operational tools. This informs
the evidence-layer positioning, not a claim of implemented Falkor/DanaOS integration
or proven vendor capability. Private interview material is not reproduced or used
as a published architecture specification.

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

The current root elapsed bound is 900 seconds. Older cohorts used a 300-second
bound and older call/tool allowances; do not apply those counts to newer receipts.
Automatic roots are episode-triggered/coalesced, not
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

**Decision now:** pilot-design discussion only. Pilot authorization requires signed
scope, data/security approval, accountable owners, gates and a total-spend cap.
The following is a **proposed negotiation starting point, not customer-agreed
acceptance, a statistical power calculation or a production qualification plan**.

### Proposed shadow-pilot scorecard

Evaluate one pipeline for four weeks **after readiness acceptance**: week 1 replay
and data checks; week 2 independent expert adjudication; week 3 operator comparison;
week 4 joint review. Integration/discovery precedes this evaluation clock.

| Proposed gate | Measurement and decision |
|---|---|
| Cases and labels | At least 20 distinct event-level cases, including at least five independently adjudicated examples each of observable leak, instrument error and benign operating change; include inadequate-coverage cases. Different checkpoints, seeds or reruns of one event do not supply independent field cases. Cases need approved independent labels or validated tests; synthetic cases remain separately labeled. This floor is not enough to certify field sensitivity. |
| Blinded comparator | Run manual, strong-fixed and agent workflows on matched evidence, randomize/counterbalance operator assignment, and conceal workflow identity from outcome adjudicators where feasible. Record unavoidable unblinding and avoid repeat-case learning. Time preparation, waiting that blocks other work, evidence review, corrections, retries and handoff separately; report elapsed completion as well as total active human handling. |
| Useful incremental value | At least 20% lower median active human handling than the stronger comparator, with no increase in adjudicated missed/false findings, unsafe recommendations or incorrect clearance. Report case counts and uncertainty; a small zero-error set is not proof of non-inferiority. Prefer fixed workflow if equivalent. |
| Safety/evidence | Zero observed unsupported safety-critical claims, leak clearances or unauthorized actions in released reports; every released location has snapshot-bound support. All inadequate coverage remains unknown, not healthy; withheld reports and uncovered leaks remain counted. An observed safety-critical breach stops the pilot for review, not threshold tuning. |
| Completion and timing | At least 90% of all admitted first attempts yield reviewable reports within 900s; disclose every retry and failure. Report median/p95 end-to-end completion and warning delivery separately. Five minutes remains a stretch target, not a passed gate. Production warning timing requires customer-defined acquisition/network budgets. |
| Cost and exit | Actual total spend stays within the signed cap; no automatic paid extension. Review handling-time benefit, error quality and total cost jointly. Too few independent cases, missing labels or inconclusive comparisons means explicitly extend by agreement or stop—not pass. No production-safety rollout follows automatically. |

### Readiness, ownership and effort

Before scheduling, name a customer integrity lead (labels, safety and approval),
instrumentation/historian owner (feeds, units, clock/arrival semantics and normal
reference), operations SME (valve/compressor context and shared failure domains),
knowledge owner (approved procedures, versions and contradictions), security/data
owner (hosted inference, access, retention and deletion), delivery lead (connectors,
identity, deployment, recovery and support), and sponsor (cap and exit decision).
One person may hold multiple roles, but none is implicitly supplied by the demo.

Require topology/chainage and sensor/gateway metadata, synchronized event histories,
quality flags and known gaps, independently labeled cases, current operating and
maintenance records, read-only access, identity/approval workflow, hosting capacity,
and data-export/retention terms. Connectors and production identity are not supplied.
Knowledge onboarding requires expert elicitation, approval/change control and a
newcomer-versus-expert transfer exercise, not merely importing documents.

**Discovery-only effort estimate:** allow 5–10 delivery person-days for schema/
connector/security mapping plus 3–5 customer SME person-days for data and case
readiness, before the evaluation. This is an unvalidated planning allowance, not
a quote, staffing commitment or connector-completion guarantee; gaps may require
materially more effort. Re-estimate deployment, identity, integration and ongoing
review/support after inspecting the actual site. Owners must accept the revised
effort, schedule and cap before work proceeds.

### Transparent total cost; no invented savings

`Pilot TCO = attributable actual Copilot entitlement + actual incremental usage/
overages + hosting/storage/network/observability + implementation/deployment labor
+ customer expert/reviewer labor + support/maintenance + agreed contingency`.

All monetary inputs, approved commercial entitlement, usage allowances/overages,
attribution of existing subscriptions, infrastructure sizing and labor rates remain
**unknown**. Obtain the actual Copilot plan/organization entitlement and provider
usage/billing records; validate permitted deployment and service use. Model/tool
counts are workload counters, not a bill. Record failed/revised calls too. A
hypothetical `input tokens × assumed rate + output tokens × assumed rate` scenario
is a sensitivity estimate only: do not substitute it for actual Copilot accounting,
add it again to that bill, or claim absent token telemetry is measured usage.
No contractual dollar quotation exists here; signed total-spend cap, allocation of
customer effort and pause/overage approval rules are prerequisites.

Capacity-value hypothesis: `eligible cases × measured active human hours saved per
case × agreed loaded hourly rate`, less full TCO. The ten-minute manual baseline is
unmeasured; the former 15-minute-saving illustration is withdrawn as inconsistent.
Freed capacity is not necessarily cash savings; no avoided inspection or field ROI
is established.

**30-minute buying conversation:** 5m problem and objections; 10m the canonical
recorded S7 investigation (measurements, competing explanations, where/when and
remaining engineer actions); 10m readiness, TCO and proposed scorecard; 5m agree
owners and the conditional next decision. Label recorded results and actual timing;
do not promise a fresh accepted answer within the meeting.

**Not implemented/supported:** live historian ingestion, production multi-user
identity, certified leak protection, plant control, DanaOS integration, local-only
inference, field reliability or validated ROI. Reviewer access to this private
repository and email submission 24h before the interview remain the owner's actions.
