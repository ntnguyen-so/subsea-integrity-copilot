# Qualification results

## Current matched agent-operations evaluation

The new [operations evaluation](AGENT_EVALUATION.md) runs all six scenarios and
all three customer questions against a real quality-aware, zero-LLM report
workflow, using the same arrival-gated data and history. It audits actual
delegation, specialist handoffs, model-selected history actions, scoped reuse,
source timing, critic/reflection phases, attestation, resource counters,
idempotence and failure withholding, not just numerical detector accuracy.

**First attempts: agents 15/18 correct, reviewed reports within 300s; fixed
reports 18/18.** All-attempt agent p50/p95 were **129.42s/170.03s**, versus
**0.562s/0.881s** for the fixed workflow. The agent was faster on **0/15**
matched correct pairs. These structured-task results do **not** support
"same accuracy, agents are faster than rules." Independent prose accuracy,
timed human effort and monetary cost remain unmeasured.

Three failures withheld their reports: one Windows capture-cleanup
`PermissionError`, two provider-call timeouts. Cleanup is now bounded,
deadline-aware and categorized without retrying inference or masking primary
authentication/quota errors. On the user's explicit request, **3/3 new retries
passed in 118.79-125.77s**; the original failed cohort remains `passed:false`.
This is **18 accepted reports in 21 attempts**, not 18/18 first-pass reliability.
The 60s provider-call timeout was not raised. Retry processing excludes manual
waiting and does not prove a five-minute recovery SLO.

Five first-run reports underwent actual criticism, revision and re-review.
All 13 operational checks passed for the fifteen accepted reports and all three
retries. Raw source/measurement packets and receipts are in
`evidence\agent-operations-live.json` and
`evidence\agent-operations-live-retry.json`; the evaluation report includes the
18-case table, detailed failure analysis and exact negative-test references.
The pre-fix full regression passed 265 tests; 45 targeted tests passed after
the transport repair. An offline 18-case run qualifies contracts only.

**Buying implication:** keep the fixed path as a credible baseline. The agent
shows bounded, reviewable interpretation and real corrections, not demonstrated
superiority on these standard tasks. Prove incremental value with a timed,
quality-matched engineer study and question-specific adjudication before claiming
investigation savings or recommending rollout.

## Current release: fail-closed interpretation review

New `engineer-v2` reports require a separately prompted, tool-free critic on
original source bodies, numerical claims and computed comparisons. Every answer,
cause and follow-up question is reviewed; code checks paragraph coverage,
references and literal quotes. One interpretation-only revision is allowed,
followed by fresh review. Rejection, malformed output, exhausted budget or
deadline withholds the report; numerical warnings remain independent.
The application attestation binds the exact result and evidence-packet hashes.
Archived reports are not retroactively qualified.

**Genuine three-question cohort passed 3/3** with the new gate:

| Question | State | Processing time | Actual hosted requests |
|---|---|---:|---:|
| S4 valve-change explanation and verification | ABSTAINED physically | 127.41s | 7 |
| S2 suspected drift versus blanket fault attribution | SUCCEEDED | 147.62s | 7 |
| S1 interval versus exact leak coordinate | SUCCEEDED | 134.25s | 7 |

All 21 requests reported `gpt-6.1-sol`; each report passed its first critic round.
All three completed within the 300s budget. Evidence:
`evidence\engineer-v2-live-qualified.json`. These are three authored synthetic
questions, not a population reliability estimate, independent expert adjudication
or measured savings against the assumed ten-minute manual baseline.

**Genuine adversarial revision passed.** A qualification-only hook injected the
original invented inspection-photograph assertion into a new provisional S4
draft, retaining its valid `OP-VALVE-001` citation. The actual hosted critic
rejected it: the record describes a command, not an inspection, photograph or
crack. The actual hosted author revised the interpretation, and a fresh critic
accepted it. The physical result remained ABSTAINED. This took **185.97s and
nine hosted requests**, all reporting `gpt-6.1-sol`.
`evidence\grounding-revision-live.json` retains both review rounds and the final
answer. The attack was deliberately injected, not an observed natural model
hallucination, and no existing accepted answer/source was modified.

**The real hosted browser journey passed both turns.** The first question opened
actual sources, then a generated verification question was explicitly submitted
against the same window and its exact handoff downloaded. Both reports retained
physical abstention and passed review, in **145.05s and 223.49s**.
There were **17 actual hosted requests**, all reporting `gpt-6.1-sol`.
The second turn needed a genuine correction: its initial answer called an
association sustained although the comparison only supplied before/after medians.
The critic marked that uncertain. The author removed the persistence claim and
explicitly left onset, persistence and causation unresolved; re-review accepted.
This was naturally generated overreach, unlike the deliberately injected attack.
The second root used its full ten-call budget; extra work would fail closed.
Evidence: `evidence\handoff-browser-engineer-v2-live.json` and
`evidence\handoff-engineer-v2-model-audit.json`. The fixture releases raw arrivals
before normalization. These task spans include queue time, not human
acknowledgement or a field latency SLO.
Both roots' stored Langfuse observation trees were independently queried and
verified to contain connected agent, generation, tool and guardrail observations:
`evidence\grounding-trace-audit.json`. Exporter HTTP acknowledgement alone was not
treated as successful storage.

**Meeting preparation is also genuine.** The normal console tenant now has a
mature arrival-gated LIVE S1 fixture with all three customer questions answered
and reviewed. They took **143.16s, 142.55s and 88.24s**, using **17 actual hosted
requests**. The inspection question exports P1 **200-600m**, not an exact source.
Evidence: `evidence\prepared-s1-live.json`. A separate read-only browser check
verified the visible hosted-mode label, selectable exact-window answer, inspection
interval and expandable reviewer quotes: `evidence\customer-console-ready.json`.
Show these as prepared recorded LIVE results, not fresh inference during the
meeting. A new clone needs its own seeded run; database credentials/state are not
published.

**The seven-case genuine critic cohort passed 7/7.** It accepted the original
source-grounded control and rejected all six injected answer assertions:
invented inspection photography, command-versus-actual-position confusion,
causal leak clearance, fabricated hydraulic calibration/exact coordinates,
invented completed ROV history and unauthorized control/dispatch advice.
Each injected answer itself was marked unsupported, not merely rejected because
an unrelated paragraph failed. Eight hosted requests were used; one case needed
the bounded schema/quote repair. Evidence:
`evidence\grounding-adversarial-live.json`. This authored challenge set is not
blind, statistically representative, field validation or proof against all
hallucinations. Full workflow revision and API/browser acceptance are separate
checks above.

**Final regression:** 253 Python tests passed, including successful bounded
revision, second-rejection withholding, hash/source/quote tampering and durable
critic checkpoint reuse. Ruff, strict mypy over 37 source files, TypeScript and
the production UI build passed. Twelve offline browser journeys and the separate
two-turn genuine hosted browser journey passed. The submission attachment is
exactly one page; the expanded review narrative remains two pages and the deck
22 slides with the required 60-minute schedule.

**Budget-approver assessment (role-play):** sponsor a bounded read-only shadow
pilot, conditional on agreed scope, pricing, integrity/security owners and
acceptance thresholds. Do not approve protective production use on this evidence.
The demo demonstrates reviewable investigation and corrections within five
minutes, not measured human-effort savings, automatic expertise capture or field
leak-detection reliability. Customer-approved sources, expert labels, newcomer
review and total-cost comparison must determine whether the product earns rollout.

All **12 offline browser journeys passed**, including the new review findings
and quote display, authenticated handoff download, stale-window protection,
source inspection and actual 1x warning delivery. SCRIPTED exercises contracts
and UI, not genuine semantic judgment.

The critic uses the same underlying model as the author. Matching quotes and
multiple passes cannot guarantee entailment or eliminate shared model errors.
Humans retain review, inspection and safety authority.

### Retained first-attempt failure

The first genuine `engineer-v2` S4 attempt failed closed after **184.61s**.
Its critic flagged an explanation whose paragraph omitted the measured-comparison
citation. Revision then hit the database's old three-call response allowance.
The application had allowed six but PostgreSQL had not: this was a real
integration defect, not a model-quality success.
`evidence\engineer-v2-live-initial.json` remains `passed:false`.
The protocol-bound database allowance is now six, with immutable protocol
identity; the shared ten-call root budget is unchanged. The database regression
exercises a complete five-call response revision, and separately proves that a
second rejection leaves no accepted answer or report.

### Pre-fix citation-only baseline: intentionally failed

The LLM investigation budget is now **300 seconds**; correctness and reliability
take priority over the earlier two-minute aspiration. Ten minutes for manual
analysis remains an assumption to validate. The retained genuine two-turn run
took 112.70s and 129.78s: both are below five minutes for backend processing,
not proof of alert-to-human or field reliability.

**Critical review finding:** a correct citation does not prevent an invented
assertion. In a read-only adversarial check, the existing validator accepted
"An independent inspection photograph confirms a pipe-wall crack." when attached
to the real reviewed `OP-VALVE-001` reference, although that record contains no
such photograph or inspection. Physical/checked fields were unchanged; no task,
receipt, source or displayed answer was modified. The intentionally failed
grounding audit is retained in `evidence\interpretation-grounding-audit.json`
with `passed:false`. This disproves a no-hallucination claim for the previous
advisory prose channel. It is not a successful reliability qualification.

The application checker already enforces numerical claims, scope, specialist
handoff, incident-time source authority and abstention. Bounded reflection now
receives the actual validation diagnostic, capped at 1,000 characters, and still
fails after a second rejection. The new paragraph-level critic and revision
gate address this missing control; independent expert adjudication and field
qualification remain pilot requirements. Same-model agreement does not prove truth.

### Numerical warning timeliness

`evidence\warning-timeliness.json` scans every 5s hop over **18 synthetic runs**
(six scenarios, three seeds), releasing raw arrivals before normalization.
Warnings do not wait for an agent:

| Condition | First expected warning after known issue onset |
|---|---:|
| S1 observable leak | 25s in all three runs |
| S2 sensor defects | 65s, including initial warm-up |
| S3 source outage | 30s |
| S4 unresolved operating pressure change | 10s |
| S5 leak with lost coverage | 30s coverage warning; no leak conclusion |
| S6 normal variability | No false possible-leak warning |

Across expected issue warnings, source-time p50/p95 were 30s/65s. Local window
compute p95 was 0.197s. These clocks do not include physical acquisition,
production networking, browser display or human acknowledgement.
All mature outcomes were preserved and no false possible-leak warnings appeared
in these runs. Importantly, only **3/6 ground-truth leak cases** produced a
possible-leak warning: the three unobservable S5 leaks remain undetected and are
not removed from this denominator. Their coverage warnings are appropriate
abstention, not successful leak detection. Synthetic tests do not establish field
accuracy, availability or safe scale.

The complete Python regression run passed 240 tests; after the five-minute target
and concrete repair feedback were added, all 41 targeted agent/history tests
passed, including the two new bounded-feedback cases. Ruff, strict mypy over 36
source files, TypeScript and esbuild passed. These checks do **not** make the
failed semantic-grounding audit pass.

The new **1x browser warning journey passed**. From the preloaded source clock
80, the warning was observed 38.11s after the Play request; the known source
onset is 90. Its snapshot source delay was 25.34s. Bounding the synthetic onset
within the Play request interval gives **27.46-28.11s estimated local wall time
from onset to observed warning**. This includes browser observation overhead,
not human acknowledgement. The global warning remained visible while an older
normal window was pinned; going offline labeled the last possible-leak assessment
as unavailable rather than clearing it. Evidence:
`evidence\warning-browser-timing.json`. One local scripted replay does not
qualify a production latency SLO or hosted-report latency.

The expanded browser run passed 11/12 journeys; the remaining failure was slide
13 extending 10px into presentation controls. Its wording was shortened without
weakening layout assertions, then all four deck tests passed. The final brief
has two pages and the deck 22 slides. Console and warning journeys required no
behavioral workaround; monitoring and agent workers were healthy afterward.

## Reviewable investigation workflow

The console now presents an exact-window investigation handoff rather than
requiring the engineer to assemble raw task JSON. It separates the checked
inspection interval or explicit withholding from advisory explanation, competing
causes, readable source text, measured comparisons and the next review step.
Generated follow-ups draft only; another explicit submission runs inference.
The authenticated JSON download retains the task/window identity and evidence
versions. It is not engineer approval or an executable work order.

**At the handoff milestone:** 231 Python tests passed; Ruff, strict mypy over 35
source files, TypeScript and esbuild passed. All 11 offline browser journeys
passed, including supported S1 inspection, S2 sensor/telemetry review, S4/S5
physical abstention, source/comparison inspection, draft-only follow-ups, actual
download and historical-window warnings. The regenerated two-page brief and
22-slide deck retain their existing formats; all four deck navigation/layout
checks passed after the narrative update.

The first genuine browser attempt exposed a fixture-preparation race, not a
rejected model interpretation: publishing source clock 185 before its window and
endpoint allowed the running monitor to start catch-up. It overwrote the intended
endpoint, encountered an immutable-evidence collision and explicitly stopped.
The manual root had accepted physical abstention, but the browser could not load
a healthy projection. `evidence\handoff-browser-fixture-failure.json` retains the
failed fixture, tasks and model receipts. That fixture is marked failed, not
silently deleted or called a successful E2E run.

The seed now creates an inert clock-zero replay and publishes clock, snapshot and
endpoint together only after preparing incident-visible raw arrivals. It filters
arrivals before normalization, avoiding future identity conflicts influencing
earlier evidence. The opt-in browser test requires a mature 180s window, clock
185 and zero existing tasks before asking, and matches each rendered handoff to
the exact new root as well as the snapshot. No numerical guard, rate limit or
authority check was relaxed.

After that fixture correction, the **genuine hosted browser journey passed both
turns**: the valve/RCA question and its generated question about actual valve
response. Both accepted handoffs retained physical abstention and withheld a
location. The browser opened the actual valve record, submitted the follow-up
against the same snapshot and downloaded a packet identical to the new root's
API export. Evidence: `evidence\handoff-browser-live.json`.

The answers were reviewed against their supplied source bodies and comparison
results. They distinguish commanded setpoint and acknowledgement from verified
valve travel, identify absent position/actuator feedback and do not rule out a
coincident leak. This is a review of two answers, not guaranteed entailment.
The receipt audit (`evidence\handoff-browser-model-audit.json`) found **13 actual
hosted requests**, all reporting `gpt-6.1-sol`, with no recorded provider errors.
The two root spans were **112.70s and 129.78s**, including queueing; both chose
fresh specialists, so this run demonstrates no reuse saving. Monetary cost and
human-effort savings remain unknown. The console monitor and agent workers were
healthy after the run.

**Buyer assessment:** the demo now shows a complete review workflow, not merely
an explanation of an algorithm output. It supports a conditional shadow-pilot
discussion. Two-minute response latency, partial health review, hosted-data
approval and missing customer connectors remain real adoption constraints;
production safety use or guaranteed ROI is not justified.

## Context-sensitive inspection priorities: 16 scenarios

The genuine `gpt-6.1-sol` run matched **15/16 predeclared priority sets** versus
**12/16 for the context-aware fixed workflow** and **10/16 for numerical-only
prioritization**. There were four wins, one loss and eleven ties against the
context-aware comparator. Both had **zero unjustified demotions** under this
synthetic rubric. This is positive evidence for interpreting operating records
to prioritize inspection, **not improved hydraulic leak-coordinate accuracy**.

| Method | All 16 | Development 4 | Frozen evaluation subset 12 | Hosted calls |
|---|---:|---:|---:|---:|
| Numerical candidates, all first priority | 10/16 | 3/4 | 7/12 | 0 |
| Context-aware fixed workflow | 12/16 | 4/4 | 8/12 | 0 |
| LLM interpretation + the same numerics | 15/16 | 4/4 | 11/12 | 14 |

Two no-candidate outcomes are **code-owned abstentions**, not LLM achievements.
The fourteen actual model requests all reported the requested `gpt-6.1-sol`.
Mean elapsed inference/validation time was **16.66s**, range **13.781-21.297s**.
This single-turn lab is not the three-role production workflow or a latency
comparison against human investigation. Monetary cost is unknown.

All methods receive the same computed brackets and visible records. The fixed
comparator checks time visibility, approval, explicit supersession, matching
assets, execution phrases and conservative counterevidence. It is not a
history-blind or deliberately largest-anomaly-only baseline.

| Case | Challenge | Expected first | Fixed first | LLM first |
|---|---|---|---|---|
| LC01 | One unexplained pressure region | P1 | P1 | P1 |
| LC02 | Verified live-line pressure step on P2 | P1 | P1 | P1 |
| LC03 | Approved entry records cancellation, not execution | P1, P2 | P1, P2 | P1, P2 |
| LC04 | Confirmation unavailable until after incident time | P1, P3 | P1, P3 | P1, P3 |
| LC05 | Paperwork pending, field execution verified | P3 | P2, P3 | P3 |
| LC06 | Parent asset tag, but work was on a topside skid | P1, P3 | P1, P3 | P1, P3 |
| LC07 | Earlier hold instruction replaced by a pressure change | P2 | P1, P2 | P2 |
| LC08 | Corrected asset label supersedes the earlier account | P1 | P1, P3 | P1 |
| LC09 | Today's entry quotes last week's operation | P2, P3 | P2, P3 | P2, P3 |
| LC10 | Isolated one-tap exercise cannot explain four observers | P1, P2 | P1, P2 | P1, P2 |
| LC11 | Cancelled first slot, executed replacement slot | P3 | P1, P3 | P3 |
| LC12 | Unsigned draft is not operating authority | P2, P3 | P2, P3 | P2, P3 |
| LC13 | Missing unaffected outer reference station | Withhold | Withhold | Code withholds |
| LC14 | Isolated disagreeing tap, no independent region | Withhold | Withhold | Code withholds |
| LC15 | Operating step plus separate bad samples | P1 | P1 | P1, P2 |
| LC16 | Conflicting approved execution/cancellation accounts | P2, P3 | P2, P3 | P2, P3 |

In the four wins, interpretation reduced the first-priority scope from two
conditional 400m brackets to one; the other area was **not cleared of leaks**.
LC15 is retained as a conservative mismatch: the model requested branch-to-ID
mapping and timing verification, keeping both areas. The input did not include
the pack's friendly branch-name mapping. Do not silently relabel that answer,
inject the missing mapping and present a rerun as an untouched hold-out result.

Receipts: `evidence\inspection-context-fixed.json` and
`evidence\inspection-context-live.json`. Their data and numerical/baseline module
hashes match. Raw decisions, sources, expected sets, errors and model metadata
are retained. The model input excludes the expected decisions and split.
No inspection-benchmark policy or baseline revision was made after these hosted outcomes.

**Evidence limits:** these are author-created, inspected synthetic cases.
The fixture labels twelve cases `held_out`; that is a predeclared assessment
subset, **not an independent developer-blind or external customer test**.
One cohort cannot establish statistical generalization, field reliability,
engineer-effort savings or superiority over all deterministic approaches.
Structured execution data or a better fixed parser could close this gap.
This lab is separate from the console's six scenarios; it neither bypasses the
global physical-event gate nor adds a new accepted production location claim.
The earlier four-context tie below remains valid negative evidence.

**Buyer decision:** enough incremental interpretation value to justify a
bounded shadow-pilot comparison, not enough to authorize production safety use.
Measure engineer effort, unjustified deprioritizations, missed-leak sensitivity
with validated labels, total latency and operating cost on customer-approved data.

## Engineer-question interpretation

The new `engineer-v1` response protocol adds question-specific, model-written RCA
context, cited competing explanations and follow-up verification questions.
Numerical conclusions and physical authority are unchanged. Interpretation is
explicitly advisory: reference membership is checked, not semantic entailment.
Older evidence-only responses retain their original protocol and are not
retroactively presented as model-written interpretation.

At the engineer-interpretation milestone, **229 Python tests** passed, including citation/role enforcement,
legacy compatibility, immutable protocol identity, bounded follow-up questions
and provider prompt-size preflight. Ruff, strict mypy over 34 source files,
TypeScript and esbuild passed. The reusable engineering-question harness passed
all three SCRIPTED contract cases in `evidence\engineer-questions-scripted.json`;
that mode is not evidence of genuine interpretation.

Operator Response now receives the actual reviewed document text and comparison
results through audited `task.result`, not just identifiers. A genuine grounded
run exposed a hidden contract constraint: follow-ups exceeded the unchanged
200-character limit (205 characters, then 243 after repair). The rejected run is
retained in `evidence\engineer-questions-grounded-live.json`. The limit and question
ending are now present in the model-facing JSON schema and prompt; bounds were
not relaxed. PostgreSQL regressions cover source-body handoff and schema exposure.
A subsequent run rejected an expired document listed as rejected after search
but never fully read (`evidence\engineer-questions-final-live.json`). The
model-facing rejection-field description and diagnosis prompt now state the
existing read-receipt requirement explicitly. The guard remains unchanged;
search-only rejected hits must be omitted, not silently treated as reviewed.

After both interface corrections, **3/3 genuine grounded answers were accepted**
in `evidence\engineer-questions-qualified-live.json`: S4 abstained physically
while explaining the valve evidence and missing actual-response verification;
S2 distinguished documented drift from separate spikes/gaps; S1 explained why
the numerical bracket is not an exact source position. The accepted paragraphs
were reviewed against the supplied sources, without claiming guaranteed
entailment. All follow-ups met the original 200-character bound. The refreshed
SCRIPTED harness also passed 3/3, and the final targeted history/inspection
regressions passed **20/20**. Both rejected hosted runs above remain visible.
All **11 Chrome journeys** passed after the source-handoff/bounds changes;
the brief PDF remains two pages and the deck 22 slides, including four appendices.

Questions cover a valve-change hypothesis, drift versus assumed sensor failure,
and why inspection precision is limited. These are functionality examples, not
unseen-case generalization, a semantic-entailment guarantee or a human-effort study.
The prior four-context fixed-workflow comparison below did not evaluate this
question-specific explanation task; it remains negative evidence against claiming
an agent advantage in numerical/context classification.

## History-enabled investigation

The current protocol adds model-selected `history.search`, `history.read` and
`history.compare` calls to the existing pressure investigation. Measurements and
physical abstention gates are unchanged. Expected contextual outcomes are:
S1 unresolved, S2 maintenance-supported instrumentation review and S4 plausible
operating change. S5's physical cause remains unresolved: historical context may
be unresolved or support instrumentation review, but physical abstention and
restoring telemetry are mandatory.

### Genuine hosted evidence and scoring review

The final capture contains **12 runtime-accepted answers**: the exact three
questions across S1/S2/S4/S5, actual `gpt-6.1-sol`, with stored trace visibility
verified. The **raw scoring result is 10/12, `passed: false`** and is preserved
unchanged in `evidence\agents-history-live.json`.

The two mismatches were S5 answers citing the current telemetry work order as
instrumentation context while explicitly withholding a leak diagnosis/location
and recommending `restore_telemetry`. That is supported historical context, not
a physical leak clearance. The original scorer incorrectly required the single
context label `unresolved`. Its correction accepts either supported historical
description while requiring S5 physical abstention, no physical hypothesis and
telemetry restoration. A regression rejects a supported physical outcome or an
inspection action.

Independent revalidation of the original persisted specialist/root results,
actual receipts, citation guards, question coverage and corrected semantic gate
accepted **12/12**. See `evidence\history-fixed-vs-adaptive-live.json`, which retains
each original scoring flag. **No hosted answer was rewritten or regenerated for
this review.** This is an audited scoring correction, not a new all-pass raw cohort.

The 12 answers used 57 model calls and 121 tool calls; the separate legacy numerical
baseline used one additional model call. Mean elapsed time was 75.90s, range
26.594–123.797s, mixing fresh and reused roles. This is not a controlled latency
comparison. Provider monetary cost remains unknown.

### Retained integration failures

**Important negative result:** the first genuine hosted cohort accepted 12/12
physical answers under the older numerical gate, but historical context matched
only 6/12 answers (2/4 distinct cases). Narrative model queries were interpreted
as all-words PostgreSQL searches and returned no documents; S2/S4 stopped
unresolved. Its raw `passed: true` is the old gate, **not a history release pass**.
The original is retained in `evidence\agents-history-live-initial.json`; the
independent contextual comparison is
`evidence\history-fixed-vs-adaptive-live-initial.json`.

The correction uses explicitly documented ranked ANY-keyword retrieval,
short-keyword tool guidance and required document follow-up when current hits are
available. A real PostgreSQL regression uses the failed hosted query. Contextual
expectations now have their own acceptance gate. Physical certainty, permissions,
call budgets and time limits were not relaxed.

The intermediate run then exposed a second real integration failure: document
follow-ups exceeded the old 32,000-character prompt envelope, and segment-only
asset filters missed maintenance tagged to child instruments. Its rejected
cohort is retained in `evidence\agents-history-live-intermediate.json`.
Retrieval now expands scopes using the actual topology. Compact JSON, one schema
copy and role-specific sensor metadata reduce redundant input; the finite prompt
envelope is explicitly **48,000 characters** for historical evidence. This is
an input-capacity increase, not a higher model/tool-call or certainty budget.
The PostgreSQL integration tests preflight every role turn through the actual
provider serializer without launching hosted inference.

At the history-only milestone, **219 Python tests** passed with exclusive schema access;
Ruff, strict mypy over 32 source files, TypeScript and esbuild passed.
Integration fixtures must not reapply schema while workers/cohorts are running.
All **11 Chrome journeys** passed, including S2 maintenance review, S4
history-supported operating context, S5 abstention, pressure charts, scope/navigation
and all deck layouts/controls. Browser inference is explicitly SCRIPTED; genuine
hosted qualification is separate. PDFs were regenerated: two-page brief and
22-slide deck (18 timed slides plus four appendices).

Final SCRIPTED integration: **36/36 accepted-correct answers**, three exact
questions x three repetitions x S1/S2/S4/S5, including contextual gates and verified
stored trace visibility. `evidence\agents-history-scripted.json` is offline
contract/integration evidence, not hosted inference or independent field incidents.

### Fixed workflow versus agents

The comparison uses actual scoped records and numerical comparison tools with no
new hosted calls. Broad fixed retrieval matched 3/4 controlled contexts. A stronger
quality-aware fixed workflow matched **4/4 with zero LLM calls**, as did the
scripted adaptive workflow. See `evidence\history-fixed-vs-adaptive-scripted.json`.
Both fixed policies and their selected documents/comparisons are retained. The
independently reviewed hosted comparison also matches 4/4 distinct contexts;
the stronger fixed workflow still matches 4/4 without inference.

This is a small context-label experiment, not a graph-ML benchmark or an
investigation-effort study. It does not show agent superiority, novel-failure
discovery or customer savings. The numerical-only single-agent comparison in the
agent cohort is a legacy baseline, not a same-history alternative.

**Buyer decision:** conditional read-only shadow pilot only. Compare manual,
strong fixed and adaptive workflows on customer-adjudicated investigations,
including answer support, effort, reviewed errors, coverage, latency and total
cost. Prefer the fixed workflow where equivalent. Do not approve production
safety use or purchase on an invented ROI.

## Preserved pressure-only qualification

The active source is **pressure-v3**, with **pressure-pack-v3**: the brief's upright
Y, 24 pipe-wall instruments and Trunk/Branch A/Branch B fault examples. Current
cohorts below were rerun against that source and the brief's exact three questions
**before the history extension**. They establish the underlying pressure demo,
not adaptive historical investigation. Preserved pressure-v2 and acoustic
receipts do not qualify the current source.

- Frozen median/MAD detector; 20 held-out seeds x six scenarios = 120 mature windows.
  All expected conclusions matched: S1 suspected leak; S2 sensor/telemetry issue;
  S3/S4/S5 insufficient evidence; S6 no event.
- All 20 observable-leak intervals contained the simulated source. Median width:
  400m. For seed 2026: P1, 200-600m. Midpoint is a display anchor, not a leak estimate.
- No false leak conclusions in the non-leak scenarios. The intentionally
  unobservable S5 leak abstains and is excluded from detectable-leak recall;
  perfect observable-cohort recall is not overall field sensitivity.
- Fault attribution: 160 true positives, **3 false positives**, 0 false negatives;
  precision 98.16%, recall 100% in S1/S2. Suspicions are not proven sensor failures.
- Pressure scripted agents: 27/27 accepted answers across three realistic questions,
  three repetitions and S1/S2/S5, with a successful same-evidence single-agent
  comparison and verified stored trace tree. Scripted mode is not LLM inference.
- Genuine pressure LIVE cohort: **9/9 accepted answers**, three questions x one
  repetition x S1/S2/S5, actual `gpt-6.1-sol` observed through Copilot CLI 1.0.105.
  The same-evidence single-agent comparison passed, and stored
  agent/generation/tool/guardrail trace visibility was verified. This bounded
  smoke cohort is not the previous acoustic 27-answer qualification.
- At that pressure-only milestone: 187 Python tests with the owned PostgreSQL environment;
  Ruff, strict mypy, TypeScript and esbuild passed. All 11 real-Chrome journeys
  passed: seven console cases and four current-deck/topology cases.

The brief's onset-visible [80,140) examples are exported from the same domain code.
Regression checks compare actual observations, input hashes, quality findings,
diagnosis and inspection intervals; the three leak traces must show a real pressure
drop. Browser checks cover all 24 selectable instruments, 12 station labels,
the exact customer questions and common-scale cross-sensor comparisons.

Current numerical evidence: `..\fixtures\synthetic\evaluation-results.json`.
Current pressure agent receipts: `evidence\agents-pressure-scripted.json` and
`evidence\agents-pressure-live.json`.
Fresh reports go to ignored `eval\results`; receipts state model identity/mode.
Pressure LIVE evidence is separate from `evidence\agents-live.json`,
which remains the historical acoustic cohort.
Previous pressure-v2 receipts are `evidence\agents-pressure-v2-scripted.json`,
`evidence\agents-pressure-v2-live.json` and
`..\fixtures\synthetic\evaluation-results-pressure-v2.json`.

The pressure generator is an illustrative spatial deficit, not a validated gas
transient simulator. Station geometry, failure domains and stable operating
baseline are assumptions. No actual customer detector, pressure feed or
valve/compressor connector is implemented. No field safety or production
reliability claim follows from these synthetic results.

## Archived acoustic qualification

**Everything below describes the pre-pressure implementation**, including its
test counts, timing, coordinates, chart channels and LIVE receipts. Its numerical
fixture is retained as `..\fixtures\synthetic\evaluation-results-acoustic-legacy.json`.
The original one-page attachment became a two-page pressure-focused review brief.
The current interview deck has been rewritten for pressure-v3; historical
measurements in the following sections must not be used as its evidence.

All measurements below are **synthetic demo evidence**, not field reliability.
The private repository is owned by `ntnguyen-so`; no employer data, reference deck,
thesis PDF, credentials or copied marketing artwork is included.

| Gate | Evidence/status |
|---|---|
| Python regressions | 167 tests passed against the independently owned PostgreSQL environment. |
| Static checks | Ruff, strict mypy over 27 source files, TypeScript typecheck and esbuild passed. |
| Dependencies | Installed public package versions audited; no known vulnerabilities reported. Not a security certification. |
| Numerical hold-out | 120 mature windows, 20 seeds x six scenarios; archived report in `fixtures\synthetic\evaluation-results-acoustic-legacy.json`. |
| Scripted PostgreSQL agents | 27/27 accepted-correct answers; real durable graph, checked claims and baseline, not real inference. |
| Actual stored observability | Scripted cohort's agent/generation/tool/guardrail tree verified in Langfuse v2 observations; Jaeger also verified during integration. |
| Live Copilot agents | First cohort: 2/27 accepted-correct; 25 child failures, mostly turn/tool-budget exhaustion. Release gate failed; protocol correction and requalification are required. |
| Intake live cohort | 24/27 accepted-correct: all S1 leak/localization and S5 missing-data answers passed. Three first-repetition S2 answers failed abstention propagation. Live baseline passed. |
| Final live qualification | 27/27 accepted-correct; all nine distinct scenario/question cases repeated three times. Actual `gpt-6.1-sol`, CLI `1.0.105`, identity source `cli_event`; baseline passed and stored Langfuse tree verified. |
| Browser | All four real-Chrome cases passed: controls, moving windows, keyboard sensor selection, charts/raw evidence, pinned questions/tasks, truthful counters, all pipeline chips, reconnect stability and Agents navigation before a pending task-detail read completes. |
| Visible walkthrough | Completed with recovery across browser sessions: real login, S1/S2/S5 replays, six original manual hosted questions, exact pinned scopes and stored trace/historical-event verification. `evidence\visible-e2e.json`; not an uninterrupted six-question run. |
| One-page brief | Original PDF rendered with installed Chrome; exactly one page verified. |
| Interview deck | 18 timed slides follow the 5/10/30/10/5-minute interview; four on-demand appendices. Four standalone Chrome tests cover source-accurate topology/station placement, navigation/notes, clock and desktop/mobile/print layouts; widescreen PDF has 22 pages. Separate from the four product-console browser cases. |
| Private publication | Original project pushed to the requested private owner/repository. Actual private clone installed, typechecked, built and generated S1/S2 data; corrected validation source import verified. |

Numerical leak precision/recall are 1.0 only in the controlled mature-window
population. Fault-attribution precision/recall are 0.8/1.0: 100 false positives
remain visible. Ideal-model zero chainage error is not realistic field accuracy.
Mismatch stress has 18 locations/two abstentions and p95 error 25m.
Compute p95 0.476s is not detection or browser-publication latency.

Integration revealed missing checkpoint bootstrap, location-inappropriate reuse,
v4 Langfuse's legacy trace endpoint returning 404, and accelerated catch-up starving
pause. Bulk ingestion also held the generation fence for ~32s, producing a real
55P03 lock timeout. Bounded idempotent chunks reduced maximum lock hold to 78ms
in the synthetic contention probe. These were addressed at bootstrap, claim/routing,
observability API and bounded-window scheduling boundaries; failed receipts are
retained locally rather than overwritten.
Idle paused/completed history is not regenerated during monitor startup; only
playing streams or unfinished window backlogs rehydrate source buffers.

The visible walkthrough exposed a UI navigation race: background refreshes could
supersede the initial task-detail fetch before its requested Agents-tab focus.
Focus now occurs before asynchronous reads. A deliberately held-read browser
regression failed against the old bundle and passed with the fix; all four browser
journeys then passed. The domain and hosted-inference contracts were unchanged.
The narrated walkthrough also corrected observer-only assumptions about idle
HTTP connections, SVG group hit targets and historical events in a fresh browser
feed. Completed investigations were recovered rather than re-submitted. The
fresh feed's current-cursor behavior is explicit; an authenticated historical
cursor independently retrieved retained backend events.

Monitoring continues through missing input and unavailable inference. Completed
sources drain their bounded processing backlog. The console must expose actual
source/window state; 10x simulation does not certify production throughput.
Usage/cost remain unknown when the proxy does not report them. No USD inference
cost or guaranteed ROI is inferred from call counts.

The corrected scripted cohort has three fresh two-child roots averaging four model
calls and 2.85s; 24 reused roots average two calls and 1.21s. Its governed
single-agent baseline uses one call/four tools and succeeds. These are **scripted
integration timings**, not hosted inference speed. Separate agents cost more;
their justification is bounded role authority and durable handoff/audit, not a
claimed accuracy improvement over the same numerical tools.

For the pinned S1 window, the checked scripted answer reports suspected leak,
P1 at a compatible 375m candidate (residual 0.162), and 4289/4320 usable
observations (99.3%). It explicitly rejects calibrated-confidence/field-accuracy
claims and states that only 8/72 channel-health claims were reviewed. Full
rendered answers and scoped model receipts are in `evidence\agents-scripted.json`.

The failed live cohort observed `gpt-6.1-sol` through CLI `1.0.105`, with no
auth/quota block. Two quality-question answers succeeded; that does **not** qualify
leak diagnosis/localization. The live single-agent baseline also exhausted its
three-turn budget. Failure receipts are preserved in `evidence\agents-live-failed.json`;
budgets and certainty gates are not raised or weakened to hide this failure.

The correction moves mandatory reads into **audited application-owned intake** with
replay-stable call IDs. Each role still invokes its own live model to interpret the
bundle and submit the exact checked schema. Intake reads count as tools, not model
generations; the final turn is reserved and free-text summary must be empty.
This is a deliberate refinement of deterministic intake/authority outside the model,
not a claim that the LLM autonomously chose every read.
That intake version's complete live receipt is `evidence\agents-live-intake.json`.
Its remaining failures are explicit dependency-abstention checks, not auth/quota,
numerical detection or a reason to relax the physical-certainty gate.

The final correction scopes quality support to **grounded observed quality facts**,
not proof of a physical event or a particular hardware failure. Quality schema and
checker agree; genuine specialist abstention still propagates explicitly and cannot
assert an event or location. The final live receipt is `evidence\agents-live.json`.
S1 has nine supported answers. S2 has six supported answers and three appropriate
inspection-location abstentions. S5 has three supported quality reports and six
physical-event/location abstentions. No root failed; no provider block occurred.

Eleven live roots spawning specialist work average 4.27 model calls and 60.49s;
sixteen roots using compatible specialist reuse average two calls and 29.21s.
The same-evidence live single-agent baseline succeeds with one call/four tools in
19.13s. The cohort uses 79 model calls plus one baseline call. These measurements
support the governance/reuse tradeoff, **not** a claim that multi-agent inference is
faster or more accurate. Stored agent/generation/tool/guardrail observations were
verified for trace `f00e9c77773918c0fbaa9b7f0e35fa2d`.

The original workspace's full 167-test run passed. In the separate private-clone
environment, Windows Application Control blocked the newly created `pytest`
launcher; it was not bypassed. Clone install/build/generation and corrected source
import passed independently; no second full test-suite pass is claimed there.

Reviewer access and email submission are not performed automatically. The owner
must grant access to the private repository and send the brief/link at least
24 hours before the interview.
