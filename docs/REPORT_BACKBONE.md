# Subsea Integrity Copilot: report backbone

This is the outline for the later engineering report and interview presentation.
The completed narrative is `REPORT.md`, with measurements in `RESULTS.md`.
This retained outline is not evidence that every proposed gate has passed.
Keep `ONE_PAGE_BRIEF_DRAFT.md` short; the report is supporting technical material.
Use `TECHNICAL_IMPLEMENTATION_PLAN.md` for the three-agent contracts, shared runtime,
LLM/statistical boundaries and CustomerOps-style Copilot CLI integration.
Use `REALTIME_STACK_AND_UI_SPEC.md` for the required CustomerOps stack, continuous
monitor, interactive console and LangChain/LangGraph/Langfuse boundaries.

## Claim-status convention

Label substantive statements as **source-backed**, **implemented**, **measured**,
**synthetic assumption**, **proposed** or **not supported**. A proposed capability
must not become an implemented capability through persuasive wording.

## 1. Executive decision: what should the prospect sign?

Open with the operational outcome, not the framework:

> Help an onshore integrity engineer distinguish a coherent possible leak from
> instrument/telemetry faults, identify a defensible inspection section, and see
> exactly where the evidence is insufficient.

Name the fictional prospect, users, unsigned objections and the limited pilot ask.
Explain that the current system is read-only and does not certify pipeline safety.

**Evidence to attach:** final one-page brief, agreed assumptions, actual demo/repo URL.

## 2. Discovery: workflow, stakes and stakeholder contract

Describe the current flow: dashboard alarm -> inspect channels and timestamps ->
check instrument/gateway health -> correlate nearby sensors -> consult integrity
engineer -> follow the existing inspection/escalation procedure.

Show where time is spent, what data is required and which decisions remain human.
Do not pretend to have interviewed this fictional customer.

| Customer role | Cares about | Main challenge | Answer/evidence to prepare |
|---|---|---|---|
| Head of Subsea Operations / budget owner | Cost, deployment timeline, inspection disruption, liability and measurable return. | "Why pay when we already have alarms? What happens when you are wrong?" | Bounded shadow pilot, capacity-value formula, false-alarm/abstention report and retained human authority. |
| Lead Subsea Integrity & Instrumentation Engineer / technical expert | Physics, sensor independence, localization, source quality, integration and reproducibility. | "What distinguishes a leak from shared failure, and where do those metres come from?" | Raw evidence -> normalization -> diagnostic rules -> candidate fit -> checked answer; confounder and model-mismatch tests. |

**Discovery questions to document:** instrument modalities and accuracy; event-time
latency; asset/topology authority; sensor spacing and shared failure domains; known
normal periods; labeled past incidents; acceptable coverage; who approves escalation;
deployment/data-residency restrictions; success measurement and pilot owner.

**Output:** a decision/evidence/authority table, not a list of hypothetical features.

## 3. Research-to-product bridge

Explain how the thesis informs marine quality flags, verified-normal baselines,
per-channel anomaly contributions and expert involvement. Cite PDF pages using the
viewer count; see `..\PLAN.md`, section 2.

Explain slide 47 as an architecture motivation. Its embedded illustration is an
underwater network, while the separately supplied picture motivates the pipeline
schematic. Neither supplies deployment coordinates.

State the extension plainly: spatial event discrimination and centerline leak
localization are new demo work. They are not thesis-proven results.

Compare CustomerOps principles to this implementation:

| Reference principle | Subsea adaptation | Cost / boundary |
|---|---|---|
| Deterministic intake and exact derivations | Unit/time normalization, conflict quarantine, counts and chainage computed in code. | Maintain explicit adapters and formulas. |
| Scoped specialists and authority outside the model | Separately scoped quality, diagnosis and response LLM tasks over numerical tools. | Serial child handoffs add proxy calls, waiting state and failure points; no unrestricted swarm. |
| Incident/task/run/result separation | Versioned investigation evidence and answer attempts. | Accepted answer is not a confirmed event or operational resolution. |
| Checked answers and bounded repair | Claim IDs, evidence membership, units, status and certainty checks. | Checker defects need negative controls; model review is not a truth oracle. |
| Customer packs and honest measurements | Site-specific geometry, vocabulary and policy; frozen evaluation. | Two synthetic packs are not two production customers. |
| Python/PostgreSQL/TypeScript and observable workflows | Same core stack; LangChain interfaces, PostgreSQL LangGraph checkpoints and OTel-to-Langfuse. | Independently qualified dependencies/services; no borrowed data, credentials or performance claims. |

Connect this to AITOMATIC's domain-aware, governed, evidence-led positioning.
Disclose that DanaOS integration is not implemented and oil-and-gas support is publicly
described as directional.

## 4. Data: imperfect evidence rather than a perfect scripted story

Describe synthetic provenance, topology, channels, sample rate and independent
failure-domain assumptions. Explain why acoustic relative power is not a calibrated
sensor quantity and why methane is domain-specific corroboration.

Show one original raw record and its canonical equivalent, with source and hashes.
Walk through the four required defect families and the shared-gateway outage.
Explain the 60-second/5-second sliding window, source clock, arrival-time watermark,
warm-up and immutable late revisions. Demonstrate an all-data-loss interval while the
clock continues; do not let missing telemetry freeze the apparent health state.

**Include these artifacts after implementation:**
- Raw/canonical example with explicit timezone and `nmol/L -> umol/L` conversion.
- Missing/spike/conflicting-duplicate examples and quarantine receipts.
- Original SVG map and sensor-to-segment associations.
- Separate evaluation-label manifest and proof it is not loaded by diagnostic code.
- Exact generation seed, source/snapshot hash and rule version.

## 5. Architecture, knowledge and control boundaries

Use `TECHNICAL_IMPLEMENTATION_PLAN.md`, sections 3-8, and the architecture in
`..\PLAN.md`, section 6. Draw the distinction between:
structural ontology, executable diagnostic procedures, numerical tools, response
reasoning, authority checks and output acceptance.

List module responsibilities, API inputs/outputs and the local evidence store.
Draw the monitor/agent worker separation and PostgreSQL transaction/event-stream
boundary. Distinguish current numerical state from each answer's pinned window.
Describe the scope gateway, shared LangGraph loop and persisted parent/child tasks.
Show actual accepted and rejected tool calls; do not substitute a diagram for execution
evidence. Explain the tool-disabled Copilot CLI transport, requested versus observed
model IDs and the fact that local CLI execution does not mean local-only inference.

Explain the simpler alternatives rejected:
- Threshold dashboard alone does not correlate topology, quality and event hypotheses.
- Unrestricted LLM over raw CSV cannot reliably own units, arithmetic or authority.
- LLM specialists are useful for evidence interpretation and separated authority,
  not for improving arithmetic; keep numerical work in deterministic/statistical tools.
- A single-agent comparison must keep the same evidence and acceptance boundaries;
  report actual latency/usage/quality rather than asserting multi-agent superiority.
- PostgreSQL/RLS/checkpoints match CustomerOps; local worker topology is not HA.
- Incident-triggered/coalesced LLM work avoids per-hop inference cost; quantify fresh
  investigation and reuse rather than inventing a real-time model latency promise.
- Langfuse is an observability/evaluation viewer, not agent-management authority;
  LangGraph and transactional workflow services manage execution.

**Evidence to attach:** named code symbols/line ranges, tool contracts, a denied-call
receipt and a complete request-to-answer trace.
Include the real Langfuse attempt/generation/tool/guardrail tree, requested/observed
model metadata, and an explicit unavailable-export warning. Do not show private
reasoning or credential-bearing captures.

## 6. Diagnostic reasoning: what does and does not support a leak?

Start with the independent health and event axes. Explain MAD residuals, minimum
scale, persistence, event-time/lag overlap, neighborhood extent, channel agreement
and failure-domain count. Publish the exact frozen thresholds.

Walk through S1 versus S2, then challenge the binary story with S3-S5.
Do not claim scattered anomalies rule out a leak or simultaneous anomalies prove one.
Show sensor faults coexisting with a suspected leak.

**Evidence to attach:** rule table, supporting/contradicting observations and tests
where one supporting sensor is removed or a gateway fails.

## 7. Localization: where do the numbers come from?

Derive the simplified acoustic excess-power fit, including coordinates, metric
distance, `r0`, noise/quality weighting and fitted nonnegative source strength.
Explain candidate search along polylines and chainage conversion.

Show a worked example generated by code: candidate -> predicted measurements ->
residual -> best segment -> compatible candidate set.

Report ambiguity, broad support and poor fit explicitly. Explain why grid spacing
does not equal accuracy and why a fit-compatible set is not a confidence interval.
Separate synthetic assumptions from validated physical models.

**Evidence to attach:** raw input values, derivation/version, candidate-score plot,
held-out segment/error metrics and crossing/model-mismatch failures.

## 8. Agent walkthrough: three customer questions

For each question include the operator prompt, selected site/snapshot, actual tool
calls, answer, evidence citations and one limitation. Use the questions in
`..\PLAN.md`, section 3.

For the ambiguous case, demonstrate a useful abstention with the exact missing
evidence and next verification step. For an adversarial wording request, demonstrate
that the model cannot convert "suspected" into "confirmed" or command a shutdown.

Show live-model versus deterministic mode clearly. Recorded runs can be a labeled
backup, not evidence that a live call just succeeded.
Show the quality/diagnosis/response task tree and distinguish a fresh investigation
from reuse of compatible saved results. The offline runtime mode is explicitly `scripted`.

Start with play/step/speed controls and the moving window; click a sensor, evidence
chip and episode to show live drill-down. Keep selection stable while the stream
updates. Show the older agent basis versus current diagnostics during slow inference.
Explain that the public AITOMATIC console was studied as a scripted marketing visual:
this original UI uses actual events/counters, not fake quorum/approvals/confidence.

## 9. Verification: qualification results, including failures

Populate a results table only after executing M5:

| Metric | Definition / population | Result | Artifact |
|---|---|---|---|
| Leak precision/recall | Event-level held-out seeds; frozen criteria. | NOT MEASURED | Pending evaluation output. |
| Segment and chainage error | All eligible S1 runs, including abstentions in success denominator. | NOT MEASURED | Pending localization report. |
| Compatible-set containment and width | Observed coverage, not calibrated confidence. | NOT MEASURED | Pending candidate output. |
| Fault attribution | Per-channel fault labels, separate from event labels. | NOT MEASURED | Pending attribution report. |
| Accepted-correct / unsupported-accepted | 27 repeated primary-question answers. | NOT MEASURED | Pending answer receipts. |
| Legitimate abstention / false rejection / failure | Distinguish usefulness from successful execution. | NOT MEASURED | Pending failure reasons. |
| End-to-end latency and usage | All attempts; unavailable token usage remains unknown. | NOT MEASURED | Pending run records. |
| Monitoring/render latency | Watermark/hop, compute, publication and browser lag separately; 1x/10x replay equivalence. | NOT MEASURED | Pending clock/window/event receipts. |
| PostgreSQL and observability | Non-superuser RLS/checkpoint scope, trace-tree visibility and failure warning. | NOT RUN | Pending integration receipts. |
| Interactive console | Replay, sensor/evidence/task drill-down, keyboard access, stale/reconnect states. | NOT RUN | Pending UI outcomes. |
| Release checks | Tests, lint, formatting, type checks and clean clone. | NOT RUN | Pending command receipts. |

Include fixed boundary tests, a model-mismatch sensitivity check and a simple
single-channel threshold baseline under the same input conditions. Do not claim
multi-agent superiority or field recall from an easy synthetic benchmark.

Keep labels hidden, split independent runs, and show unsuccessful targets. A grader
correction must not be described as an agent improvement.

## 10. Senior engineering ownership: one real failure and its fix

Reserve one concrete example from implementation, not an invented story:

`Observed failure -> reproduction -> root cause -> alternatives -> preserved
invariant -> surgical change -> positive and negative regression -> remaining limit`

Good candidates are unit conversion, common-mode missingness, crossing ambiguity or
an answer checker confusing an estimated location with a confirmed event.
State what you designed, what AI tools helped implement, what you reviewed and what
you actually measured. Commits and tests substantiate behavior, not every authorship
or work-history claim.

## 11. Commercial case: cost, timeline, risk and the bounded close

Use the transparent capacity-value and break-even formulas from `..\PLAN.md`,
section 9. Label all volumes, savings and prices illustrative. Separate engineer
capacity from cash savings; exclude avoided disasters from the base case.

Present the conditional four-week pilot, customer prerequisites, proposed scope,
measures, owners and explicit stop/go conditions. Discuss what an absent real-leak
sample can and cannot establish.

Answer the four principal objections directly: value beyond alarms, false-positive/
false-negative risk, data sovereignty, and integration burden. Tie each answer to
evidence or a pilot prerequisite rather than a promise.

## 12. Production transition and multi-account delivery

Describe which components can be reused, which require site discovery and which
have not been built. Cover ordering, late evidence, idempotency, authentication,
authorization, worker ownership, retention, monitoring, rollback and safety boundaries.

Include the second synthetic pack and the repeatable account engagement cycle.
Add proposed product-engineering tickets with reproduction, impact, workaround,
contract proposal and qualification test. Do not call them confirmed platform defects.

## 13. Assumptions, limitations and references

Keep a visible assumption register: sensor capability, verified-normal data, spatial
coverage, failure-domain independence, fixed geometry, simplified propagation, gas
pipeline context and source authority.

List limitations: synthetic-only evidence, no certified detection, no precise
triangulation, no real integration, no certified production/HA isolation, no proven customer ROI,
no DanaOS implementation and possible model/checker error. Avoid generic disclaimers
that obscure the particular failure modes.

End with concise source attributions and links to original code/evaluation artifacts.
Do not publish the supplied PDFs, slide art or private project content.

## 14. Submission package and meeting choreography

Required submission: finalized one-page brief, accessible GitHub link, short README
with prerequisites/startup/three questions, and submission at least 24 hours before
the meeting. Do not send email or create a public repository during the planning task.

| Interview time | What to show | Intended result |
|---|---|---|
| 0-5 min: problem | Prospect, workflow, unsigned objections and why your marine research is relevant. | Customer recognizes a real operational decision, not a generic chatbot. |
| 5-15 min: demo | 1 min replay/window controls; 3 min leak/location; 2 min scattered faults; 2 min gateway outage; 2 min evidence/task/trace drill-down. | Three questions, real sliding monitoring, visible defects and no missing-as-leak shortcut. |
| 15-45 min: technical deep dive | Data/clock (5); quality/event reasoning (6); localization (6); agents/PostgreSQL/Langfuse/scope (7); evaluation and one regression (6). | Every conclusion/number is traceable; monitor latency and model latency are distinct. |
| 45-55 min: business | Capacity-value sensitivity, conditional timeline, integration/security prerequisites, risk boundaries and pilot ask. | A low-risk, measurable reason to sign a pilot, not blind trust in synthetic accuracy. |
| 55-60 min: out of role | Ask how FDE/product ownership is divided; how ontology changes are qualified; what successful first-90-day delivery looks like. | Clarify the actual role and platform-development expectations. |

Rehearse without internet dependency; keep a labeled deterministic/recorded backup.
Prepare one whiteboard drawing and bookmark the ingest, diagnosis, localization,
gateway, answer-check and evaluation code. Do not read a long report during the meeting.
