# Qualification results

## Agent role and contextual legend recheck

Six agent-contract cases and six browser journeys passed across the initial
and corrected cohorts. S1 checks require a suspected-leak result and a supported
200-600 m P1 inspection interval; S2 contract checks require sensor/telemetry
assessment without a location claim. These are scripted functional checks,
not hosted accuracy measurements.

The retained genuine hosted S7 report was reopened without new model calls:
it assesses leak, instrumentation/telemetry and operating-change explanations,
abstains from a final cause, and withholds the inspection interval. Pending and
mismatched reports likewise cannot release an interval or its legend key.

Both modes retain Pressure anomaly and Missing value as the raw legend.
Redundant normal, selected and unassessed keys were removed. Reviewed-pattern
and inspection-area keys appear only when their matching overlays are drawn.
The obsolete red-cross explanation was removed from the map notes.
Pressure chart alert labels use the same Pressure anomaly and Missing value
wording as the map.

The first cohort had five passing browser journeys and one assertion failure:
the S1 scripted fixture supplies one operating-change alternative, not the three
alternatives in the genuine hosted S7 report. Its assertion was corrected to
check the actual fixture, retaining the required leak hypothesis and interval,
and the paired S1 journey passed. Ruff formatting, lint, TypeScript and the
production build passed.

## Simplified sensor alert categories

The shared map and sensor table now show only pressure anomalies and missing
values; excluded unusable readings use the **Missing value** label. Spike,
drift and paired-disagreement screening is retained in investigation evidence,
not presented as a separate quality marker or confirmed sensor fault.
The two S2 workflow checks passed. The pressure map/chart/legend and contrast
check initially exhausted its 180-second fixture/request budget, then passed
with a 420-second budget. TypeScript and the production build passed.
Earlier UI captures below document their recorded revision, before this change.

## Shared monitoring interface and agent-only interpretation

Both customer modes now retain the same layout, tabs, controls, map legend,
sensor conditions/order, comparison defaults, evidence access, coverage metrics
and detector warning. The inactive mode keeps the investigation workspace
visible and honestly reports no agent execution. Question submission is rejected
explicitly by the server without an LLM call; the shared form is not hidden.

Raw pressure and missing-value markers remain numerical observations.
Agent-reviewed regional patterns and inspection intervals require an accepted
handoff matching the selected generation, window, input hash and pack/baseline/
parameter versions. Pending, failed, unavailable or mismatched work cannot
release an interval. A valid historical report cannot annotate a different live
window. Numerical localization remains an auditable tool constraint, not a
pre-agent answer or a confirmed physical leak coordinate.

The shared detector banner reports pressure/quality alerts in both modes,
preserving coverage-loss warnings and elevated attention for a strong pressure
screen without presenting a causal diagnosis. The agent report is the separate
knowledge-guided leak/instrumentation assessment and inspection recommendation.

Backend qualification passed **33 cases**: the 25-case monitoring suite and
eight independent warning cases. A new paired API case verifies matching
pressure/quality evidence and warning content while alert-only admits no tasks
and neither unworked arm reserves model calls. Ruff, backend typing, TypeScript
and production build passed.

Eight distinct browser journeys passed across the initial and corrected
cohorts: matched S7 interface/evidence, retained hosted-report reopening,
S1 geometry/manual comparison, failure-safe warning timestamps, mobile layout,
compact layout, matched S1 workflows and pending/mismatched handoff rejection.
The initial S7 preparation failed because its chart was not ready within 15s;
no parity comparison occurred in that attempt. Preparation now waits for the
exact completed window and its chart (up to 45s), rather than accepting a
partial inspector. The corrected S7 journey also verifies identical default
comparison instruments and raw/canonical evidence categories.

The parity artifact export was corrected to retain both already-compared Live
views before navigating to Evidence. A separate read-only recapture confirmed
the stored interface/evidence equality and unchanged task/model/tool counters.
The matched S7 arms are **SCRIPTED UI fixtures**, not hosted-model quality or
field throughput evidence. The separate actual retained hosted report was
reopened in the final interface without new inference.
Receipts: `evidence\unified-mode-parity.json`,
`evidence\unified-ui-initial.xml`, `evidence\unified-ui-corrected.xml` and
`evidence\unified-ui-final-view.xml`. Current retained hosted view:
`assets\unified-agent-investigation.png`.

## Anomaly-paused investigations

New API/UI assisted runs pause the synthetic source at a newly raised detector
alarm after warm-up, pin the exact window and admit fresh hosted specialists.
10x changes simulated source pacing, not model latency. The server rejects
Play/Step until matching work is terminal; completion stays paused for explicit
Continue monitoring. Unavailable admission permits an explicit Continue without
report, retaining detector warnings. Persistent flags alone do not retrigger.
The early alert can be instrumentation-only or insufficient evidence: pausing
does not manufacture a mature leak footprint. Old recordings retain continuous
behavior and immediately display their explicitly labeled saved reports.

Pressure, gap/excluded and quality symbols now match across customer workflows
for matching input windows. They are numerical data facts, not instant LLM
discoveries. Raw missing readings remain visible even below the >10% missing
fraction used as an automatic incident trigger.

The CustomerOps reference API and frontend were already running, but their
existing storage containers were stopped. Starting those existing containers
restored `/healthz` to `ok` with integrity `ok`, without resetting reference data
or replacing its processes. The adopted pattern is server-owned work, persisted
public progress, explicit start/resume versus saved results, and no fabricated
progress percentages. The reference frontend is at `http://127.0.0.1:18083`.

Backend qualification: **24 distinct monitoring integration cases** across the
initial suite and final targeted edge-case check, including accelerated
first-alarm freezing, locked controls, reviewed continuation, unavailable-agent
continuation, restart-before-dispatch recovery and late-arrival drainage after
the final source window; **51 store/history integration
cases**; **39 agent/replay/warning unit cases**. Two database-dependent agent
cases were skipped in the separate environment-free unit invocation. Ruff,
backend typing, TypeScript and the production dashboard build passed.

Browser qualification passed the matching-S7 raw-marker comparison and a new
**live 10x** assisted run. At source **+100 seconds**, the source stopped on the
**+95-second window**. Across **26 recorded progress observations** its source
clock stayed exactly +100s. Play/Step were locked while actual work progressed.
The report completed in **159.573509 real seconds**, with **7 hosted model calls,
16 tool calls and no reused specialist tasks**. The report abstained from a
physical diagnosis/inspection interval, discussed a connected P5 pressure
pattern and competing instrumentation effects, and passed source-grounding
review. This is not a confirmed leak diagnosis or an accuracy estimate.
The earlier +110-second workload is different; these times are not a controlled
performance comparison.

A separate read-only browser check reopened that actual retained run after the
final UI wording update, waited for matching map/trend evidence, verified
Continue monitoring was available, and confirmed unchanged task/call counts.
No inference was repeated for that recorded-result check.
Eight distinct browser journeys passed across the correction cohorts, including
existing same-alert workflow comparison, public handoffs, unmatched-record
rejection and mobile layout. The initial compact-view test caught the added
progress strip exceeding its old 450px map-top bound (534.06px). The policy now
shares the existing clock line; the revised layout check requires the map in
the upper half of the 1100px viewport and the assessment directly after it.
That check and the final desktop/mobile recorded-result check then passed.
Receipt: [`evidence\anomaly-paused-hosted-current.json`](evidence/anomaly-paused-hosted-current.json).
Current rendered view: [`assets\anomaly-paused-investigation.png`](assets/anomaly-paused-investigation.png).

## Joint-pattern RCA and knowledge: current revision

The current S7 source has a graded near/far pressure footprint, staggered
impulses, intermittent offsets, plausible flatlines and shared gateway gaps.
The old narrow-profile **P5 600-1000m** qualification below is historical and
does not qualify this revised source. Numerical ambiguity or withheld location
is a valid outcome, not a reason to tune data back to the old bracket.

The diagnosis agent now receives measurements for all 112 instruments and
chooses joint comparisons of up to eight instruments. Results retain bucketed
pressure deltas, usable counts, paired-complete correlations/overlap, topology
distances, extrema and largest adjacent steps. No missing-value interpolation,
source coordinates, causal labels or wave-speed claims are provided.
Agent-authored regional assessments are distinct from the numerical screening
label and require actual comparison plus applicable knowledge references.

Five versioned research-curated cards encode guidance, prerequisites,
counterexamples and a reusable investigation procedure. Full immutable packets
are pinned to root/children; scope, status, time, declared conflicts and lineage
are checked. These are not SME-approved operating procedures. An undeclared
semantic contradiction is not automatically detected. A grounded report is
not independent proof of RCA correctness.

The first hosted knowledge-on/off pair on this revision **failed in both arms**
on oversized final diagnosis input: 62.77s off and 62.23s on, five reserved model
attempts and twelve tools each. This is a transport qualification failure,
not evidence of RCA accuracy. Original receipt:
`evidence\knowledge-live-initial.json`.

The second hosted pair, after initial handoff compaction, also failed:
knowledge-off **105.33s, six model attempts, twelve tools** (an unknown limitation
code required repair, then exceeded input size); knowledge-on **63.55s, five
attempts, twelve tools** (final diagnosis input size). Receipt:
`evidence\knowledge-live-second.json`. Subsequent corrections expose the allowed
limitation vocabulary, reserve final-only replies when tools are exhausted,
avoid repeating the supplied schema during repair, and encode structured context
and tool data as JSON objects rather than doubly escaped JSON strings.

The corrective transport work uses lossless columnar measurements, removes
already-completed intake tools from offered schemas, binds no tools on final-only
turns and uses phase/role-scoped knowledge excerpts. The complete pinned
knowledge and raw tool audit remain intact. The shared tool-result bound is
16 KiB rather than 12 KiB; the 48,000-character prompt, root 300-second deadline,
ten model calls and eighteen tool calls remain unchanged. Oversized results
produce explicit error receipts, not false successes or silently truncated data.
Current hosted qualification and independent reviews must be read separately
from older success receipts.

The third pair reached accepted diagnosis tasks in both arms but withheld both
operator reports: **178.88s off / 168.34s on, eight model attempts and sixteen
tools each**. Reflection duplicated critic quotes; the knowledge critic's repair
exceeded context size. Receipt: `evidence\knowledge-live-third.json`.
The corrective views retain original guidance, applicability, verification,
counterexamples, limitations and review basis while leaving capture metadata in
the full pinned packet. Reflection receives every critique reason and verdict,
not duplicated support quotes; original measured/source intake remains available.

Independent engineering review also found that the discovery table mixed
threshold-conditioned and whole-window magnitudes. It now uses **the same final
20-second usable median relative to verified-normal baseline for every
instrument**, with explicit period and sample counts. The old conditional
statistic remains only in the unchanged numerical detector/locator. A regression
checks all 112 values against source observations, including the weak P5 tail.

The complete current backend regression passed **325 tests**, with Ruff, mypy,
TypeScript and the UI build passing. This verifies implementation contracts,
not live reasoning accuracy or measured customer value.

The fourth pair accepted knowledge-off (**173.17s, seven model calls, sixteen
tools**) with actual P2/P7 records and P5 comparison, but withheld knowledge-on
(**163.97s, eight attempts, sixteen tools**) on reflection input size:
`evidence\knowledge-live-fourth.json`. Failed-arm utility flags mean no accepted
handoff was available; they do not prove that no source read occurred.

Reflection now returns only a typed `EngineerInterpretation`; the application
merges it into the original candidate and revalidates the entire result, preserving
every checked field by construction. The reflection view omits duplicated routing
metadata. **95 focused workflow/history/transport tests passed** after that
refinement, including two eight-instrument comparisons, diagnosis schema repair,
an initially fabricated assertion, one reflection and final critic acceptance,
all within the original ten-call root ceiling.

Independent engineering and buyer reviews initially rejected a purchase-ready
claim: joint evidence, causal independence from the detector, matched
counterexamples, a strong fixed comparator, SME approval and real total handling
time were missing. The implementation addresses evidence/interpretation
separation, but field accuracy, engineer-time savings and willingness to pay
remain unmeasured. Reviews must not be relabeled as approval.

The fifth knowledge pair produced one accepted knowledge-on worked example:
**208.47s, eight model calls, sixteen tools**. The report actually read P2
operating and P7 maintenance records, compared six graded P5 observers against
quiet P4/P6 controls, and separated possible P5 physical disturbance, P7
instrumentation context and P2 operating context. It withheld an inspection
bracket. Knowledge-off on matching raw input was **grounding-rejected,
245.91s, ten model calls, sixteen tools**, including unsupported contextual
assertions after revision. The pair therefore **did not pass**:
`evidence\knowledge-live-current.json`. This is not a controlled knowledge-benefit
or accuracy result.

The independent AI engineering role-play accepted the reasoning of that single
synthetic run, with important limits: only three affected P7 taps were compared,
the weak cross-junction P4-ST1 response was not directly tested, and repeatable
completion and timing discrimination were not established. The buyer role-play
supported a pilot-design meeting, not purchase authorization. These are neither
pipeline-SME approval nor actual customer willingness to pay.

The frozen joint-timing probe changes cross-instrument timing while preserving
each instrument's before/after value distribution. Its first attempt failed
transport in both arms (`evidence\joint-timing-live-initial.json`). A second
implementation did not complete both arms
(`evidence\joint-timing-live-second.json`). A third also failed both diagnosis
prompts, at **49,096 and 49,195 characters** against the unchanged 48,000-character
bound (`evidence\joint-timing-live-third.json`). These are failed qualifications,
not evidence that the agent distinguished the timing patterns.

Lossless reference encoding now avoids repeating a claim value when its sole
evidence value is identical. The full source and persisted audit remain intact.
Diagnosis additionally caps cumulative normalized successful tool-result JSON
at **21 Ki characters**, rather than assuming per-result and call-count limits
bound the whole context. Optional reads exceeding that cap return no result and
an explicit `context_budget_exceeded` receipt. The limitation is mandatory in
the report; an unread source cannot support a citation. This does not increase
the root deadline, model/tool count or provider prompt size.

The final aggregate-budget revision passed **328 backend tests**, including
mandatory disclosure of denied reads, lossless transport and the bounded
two-comparison/repair/reflection path. Ruff, mypy, strict TypeScript and the
production UI build also passed. These checks do not grade live causal reasoning.

The fourth frozen timing execution completed both arms, accepted as
**ABSTAINED**, with matching individual before/after distributions:
`evidence\joint-timing-live-current.json`.

| Timing arm | Actual handoff | Wall time | Model / tool calls |
|---|---|---|---|
| Aligned | All eight instruments share the approximately -0.55 bar pulse at +70 to +90 and recovery; reported zero-lag Pearson correlations are 1.0. | 169.84s | 7 / 16 |
| Staggered | Identical -0.2746 bar split-median changes conceal ST1/2's early recovering pulse and ST3/4's later decrease; between-group zero-lag Pearson correlation is -0.501. | 228.05s | 9 / 15 |

Both reports challenged the maintenance record's timing and affected scope,
retained competing causes and withheld an inspection interval. The aligned
report retained the explicit context-budget limitation. The question supplied
the eight instruments, window and split: this is scoped temporal interpretation,
not autonomous discovery, hydraulic propagation measurement or superiority over
strong fixed analysis. Two authored probes cannot establish repeatability,
population accuracy or a causal knowledge benefit.

The final independent AI engineering role-play found no remaining substantive
blocker **for this synthetic investigation meeting**, after checking the actual
profiles and citations. The AI buyer role-play supported **a buyer meeting and
pilot-design discussion**, conditional on faithful dashboard qualification,
repeatable completion with failures included, an SME-adjudicated strong-fixed
and total-handling-time comparison, and agreed data/commercial/exit terms.
Neither constitutes human SME approval or purchase authorization. Review
summary: `evidence\joint-pattern-review.json`.

The first current browser batch passed original-brief geometry, larger-network
manual work, timestamp/failure handling and light-theme/legend checks, but three
journeys still expected the old "Agent report ready" wording. After correcting
that assertion, the knowledge-to-recorded-check journey passed; two further
stale assertions exposed changed record terminology and a no-longer-visible
critic decision. The dashboard now explicitly renders the **actual final
source-grounding decision**, not an inferred approval. Initial receipts remain
`evidence\joint-pattern-browser-initial.xml` and
`evidence\joint-pattern-browser-label-correction.xml`.

Operational copy no longer calls the workspace a demo or adds selling-process
language. Research-derived guidance, synthetic telemetry, read-only authority and
the absence of pipeline-SME approval remain explicit. Editorial guidance changes
produce a different content-hashed packet; historical pinned sources and failed
receipts are not rewritten.

The corrected offline browser cohort passed all **seven distinct journeys**
across the initial four passes and final three corrected checks
(`evidence\joint-pattern-browser-final.xml`). This includes actual guidance
links, regional findings, two customer workflows, faithful source-grounding
status and withholding mismatched handoffs.

A fresh **automatic hosted S7** dashboard attempt nevertheless withheld its
report: diagnosis exceeded the input bound during its one schema repair,
**48,321 characters** against 48,000. The eight reads themselves totalled about
20,191 normalized characters; the rejected draft was unnecessarily replayed
alongside all source evidence. This live failure is separate from the successful
backend worked example and frozen probes. Receipts:
`evidence\joint-pattern-hosted-ui-initial.json` and matching XML.

Repair requests now regenerate a complete result from the original source
messages and exact validator feedback, without replaying the invalid draft.
The draft remains in the durable graph audit. Every source/tool receipt is
preserved, as are the single-repair, model/tool-count, elapsed-time and prompt
limits. A focused regression checks projection and audit preservation.
Lossless value references also distinguish JSON booleans from Python-equal
numbers, including nested values; four edge cases and the five larger-network/
knowledge/bounded-reflection integration cases passed.

The final repair-projection backend cohort had **331 passes and two
wording-only failures**: alert-only integration cases expected "does not
classify" while the revised banner used "do not classify." Restoring compatible
operational wording made both unchanged cases pass. All **333 distinct backend
cases** therefore passed across that cohort and the two-case corrective run,
not a clean first attempt. Ruff and mypy passed. Receipts:
`evidence\joint-pattern-backend-release-initial.xml` and
`evidence\joint-pattern-alert-grammar.xml`.

The publication scan removed an authenticated request call log from the older
`extended-network-browser-initial.xml`; its failed test outcome and timing are
preserved. Authentication material is not part of publishable evidence.

The next fresh automatic hosted S7 dashboard qualification **passed**:
**233.70 seconds from admission, eight hosted model calls and sixteen tools**.
The complete browser journey took 454.08 seconds, including preparation of both
matching alert-only and assisted replays; that is not model latency.
The generic automatic question did not supply a sensor list. The agent selected
graded P5 observers plus weak P4-ST1 and quiet P6 control, contrasted P7 odd/
even stations against maintenance scope, and compared P2's positive operating
response against P5's negative change. It read three operational records,
executed two joint comparisons and cited four pinned guidance cards.

The UI showed actual admission/report timestamps, 3:53 processing elapsed,
specialist roles, P5/P7/P2 regional explanations, source-grounding acceptance,
recorded guidance-to-check links and the unchanged manual map/trend workspace.
It retained physical uncertainty and **withheld a qualified inspection interval**.
The automated browser check also verified matching input hashes, actual
maintenance/operating citations, no displayed inspection interval, and accepted
grounding. Evidence: `evidence\joint-pattern-hosted-ui-current.json`, matching
XML and `assets\knowledge-guided-investigation.png`.

This is one fresh accepted automatic run after a recorded failure, not a
repeatability or customer-value estimate. The frozen timing probes remain
scoped reasoning examples; knowledge superiority, field accuracy, SME approval
and total human handling-time savings remain unestablished.

After inspecting the fresh receipt and screenshot, the independent AI
engineering reviewer reconfirmed meeting-scope satisfaction with no new
substantive blocker. The AI buyer reviewer marked the faithful-dashboard gate
met and supported a buyer meeting/pilot-design discussion, with no new material
objection. Repeatability, strong-fixed comparison, total human handling time,
human SME review and actual data/commercial terms remain purchase gates.

## Historical extended-network workload (earlier narrow-profile S7)

S7 adds a separately versioned **11.2 km, seven-segment network, 56 paired
stations and 112 pressure instruments**. The brief's original Y and S1-S6
remain unchanged; the historical six-case evaluation cohorts explicitly retain
their original membership.

One localized physical pressure footprint coincides with three distributed
drifts, three spike sources, three intermittent streams, an invalid-value
source, an eight-tap shared-gateway offset and a positive operating-pressure
transition. A separate fictional corpus retains approved operations,
superseded calibration instructions, a revised shared-gateway record, a draft
valve proposal and an incomplete-log coverage statement. Source positions are
not exposed as diagnostic evidence.

At source +140s, three tested seeds supported **P5, 600-1000m**; the numerical
tools, not the LLM, compute this inspection bracket. Removing its four
supporting observers did not turn the remaining gateway/operating disturbances
into a suspected leak. This is a counterfactual check on the synthetic workload,
not a multi-leak or hydraulic-validation result.

All **148 targeted backend cases passed**. An initial run exposed a regression
where the new metadata helper incorrectly required generated geometry for
small test fixtures (11 failures). Restricting that path to larger networks
restored existing behavior; both receipts are retained. The larger-network
tests also check separate corpus admission, pinned history geometry, bounded
tool outputs and representative context that includes every branch. Agent
budgets remain unchanged; health review is partial, contextual metadata is
limited to 24 instruments, and all 112 computed findings remain available.

The initial browser batch passed original-brief geometry, extended-network
branch focus/manual comparison, and scoped agent-work journeys. Its two-mode
case exceeded its 180s total test timeout while preparing two 185s replays.
That comparison now stops both sources at the sufficient, identical +115s
point (window +110s), without changing the report deadline. Preparation errors
redact authenticated request logs. The original sanitized failure is retained,
not relabeled as a pass.

## Buyer-visible agent work

The buyer audit reproduced the problem: an inspection interval appeared before
the LLM completed, while actual source checks and specialist handoffs were hidden
in the Agents workspace. The default Live view now separates numerical results
from an automatically triggered investigation with a real elapsed clock,
three specialist status/handoff cards, actual search intent and keywords,
opened records, measured comparisons, source-backed quotes, competing causes,
critic outcome and an engineer verification question. A stable activity strip
above the map links directly to the work; raw processing timestamps remain
available without expanding all diagnostics by default.

Automatic receipt reads are generation/task/basis scoped and coalesced. A
mismatched input hash withholds the displayed source findings without clearing
the detector warning. Browsing a source stays open across unchanged projections.
No inference, simulation time, source review or findings are manufactured by
the UI.

The initial focused browser run passed six of seven journeys; its failure
incorrectly assumed the scripted fixture supplied three competing causes.
The UI correctly showed the one actually recorded. The assertion now compares
with the exact handoff, and that journey passed on rerun. Receipts:
`evidence\buyer-agent-ui-initial.xml` and `evidence\buyer-agent-ui.xml`.
TypeScript and the production build passed.

A **fresh automatic hosted S4** investigation then completed in **134.59s,
seven model calls**, with accepted grounding. The numerical result remained
`insufficient_evidence`, with physical abstention and no inspection location.
The investigation agent independently searched, read and cited **OP-VALVE-001**
and executed a measured pressure comparison. It assessed an operating change
as plausible, requested operating-record verification, and did not exclude a
coincident leak. This contextual finding is not supplied by the detector alone.
The live UI showed elapsed processing while source time remained paused,
actual specialist progress and the separate grounding-critic phase, then the
inline source-backed findings without visiting Agents. Mobile overflow and
browser-error checks passed. Evidence: `evidence\buyer-agent-live.json`;
screenshots: `assets\agent-work-live-running.png` and
`assets\agent-work-live-findings.png`.

Historical S4 assessment: this supports investigating an instrumented **read-only pilot**, not a
production-safety purchase or proven labor-saving claim. Partial health review,
incomplete operating records, synthetic physics and same-model criticism remain
explicit limitations. A larger topology is a separate workload demonstration,
not evidence that LLMs outperform numerical detection.

## Two customer workflows, not two inference settings

The customer-facing selector now has exactly two choices:
**Sensor alerts only** and **Agent-assisted investigation**. Scripted versus
hosted execution is no longer a customer-facing setting. New agent-assisted UI
runs use real hosted inference; existing offline fixtures retain honest SCRIPTED
labels when inspected.

The alert-only view flags individual instruments and supports manual trend/raw
inspection. It does not show a combined leak/malfunction diagnosis, correlated
support diamonds, an inspection interval, agent reports or agent questions.
Engineers must connect timing, location and operating context themselves.
The product view adds cross-sensor numerical correlation, leak-versus-
instrumentation assessment or explicit uncertainty, supported inspection
intervals, and source-reviewed agent investigation and handover. LLMs do not
invent physical measurements or leak coordinates.

The selected workflow is persisted and immutable per replay. Alert-only runs
never dispatch automatic agent work, and manual question admission is rejected
server-side. No LLM is called for that workflow. Both views use the same
synthetic source and existing per-sensor detection. The shared audit kernel
retains numerical calculations behind the alert-only view: this is a controlled
workflow demonstration, not a benchmark of the customer's installed software.
The assumed current process is from the brief; customer connectors remain unbuilt.

**38 monitoring/store integration tests and eight warning tests passed.**
Coverage loss and warm-up remain explicit in both workflows. Normal physical
conditions may still contain individual sensor flags; a lack of a correlated
event is not the same as no outlying samples. Workflow admission, persistence
and existing monitoring behavior are covered by
`evidence\customer-modes-backend.xml` and `evidence\customer-modes-warnings.xml`.
Ruff, strict mypy and TypeScript checks and the production UI build passed.

Browser regression covered all **23 distinct offline journeys** across the
cohort and corrective checks, not a clean first attempt. The cohort had
**22 passes and one failure**: a paused replay did not reliably recognize
browser-offline emulation from EventSource callbacks alone. Warning and clock
freshness now also check the browser's offline state. The unchanged disconnect
assertion and the expanded two-workflow journey then **both passed** on the
final UI build, including raw inspection without combined claims in alert-only
mode. Receipts: `evidence\customer-modes-browser-initial.xml` and
`evidence\customer-modes-browser.xml`. An earlier manual journey raced the end
of finite 10x playback; its 5x correction requires explicit PAUSED state, without
increasing timeouts. Both original failures remain described in
`evidence\customer-modes-initial.json`.

The corrective 1x replay observed its warning 40.94s after Play, with
**26.48-30.94s estimated local wall time from known source onset**. This is a
single scripted-agent local timing observation, not hosted-report latency or a
field SLO. Its separate receipt is
`evidence\customer-modes-warning-timing.json`; earlier timing evidence is retained.

A read-only comparison uses the original genuine hosted S1 report and an actual
alert-only replay with **identical input hashes at source +110s**. The baseline
has **zero agent tasks**. The hosted report contains **two document reads, one
included pressure comparison, seven hosted calls and 145.08s from admission**,
with its original accepted critic record and exact P1 200-600m handoff. No new
inference was requested for this UI review. Evidence:
`evidence\customer-modes-recorded-review.json`.
Screenshots: [individual alerts](assets/dashboard-sensor-alerts.png),
[agent-assisted view](assets/engineer-dashboard-live.png), and
[same-alert workflow comparison](assets/dashboard-workflow-comparison.png).

The comparison exposes actual source/review receipts and a reusable handoff,
not inferred savings. Ten-minute manual investigation is still an assumption;
human review time, onboarding benefit, field accuracy and total monetary cost
remain unmeasured. The separate fixed-workflow benchmark below remains a
credible alternative, not equivalent to this illustrative alert-only workflow.

## Light theme and consistent sensor meanings

The readability review replaced the dark palette with white panels, dark text
and larger labels. Matching SVG legend symbols now use the map's actual marker
classes rather than a triangle that the map never drew. Individual threshold
excursions appear amber on both map and trend, even without a qualifying event.
Quality concerns have a red cross, selection an independent blue ring,
missing/excluded readings a dashed outline, and unassessed instruments a grey
fill rather than an apparently usable green marker. The instrument table keeps
pressure anomalies alongside missing/quality conditions. These are evidence
flags, not confirmed physical diagnoses.

The three-area default remains; chart headings and keys share a row when space
permits, and the instrument list scrolls rather than reducing text size. A long
hosted conclusion can extend below the first viewport: the preserved report's
assessment starts at 868.25px and ends at 1145.20px at 1600x1100. This deliberately
preserves readable, untruncated uncertainty instead of promising all report
lengths fit one screen.

The preserved genuine hosted S1 result was reviewed read-only across Live,
Agents, raw Evidence and Audit. Its original P1 200-600m handoff and accepted
critic record remained accessible, with no browser errors. Evidence:
`evidence\dashboard-light-hosted-review.json`. No new inference was requested;
this is not a new model-performance evaluation or a human-usability study.

All **22 offline browser journeys passed** in 11.9 minutes. Focused additions
check real S1 map/chart/legend color correspondence and representative text
contrast of at least 4.5:1, real S2 quality-cross correspondence, and all 24 grey
unassessed markers during warm-up. Existing geometry, comparison, live/pinned
evidence, timestamps, failure withholding, keyboard, mobile, report-review and
warning workflows also passed. TypeScript and the production UI build passed.
Evidence: `evidence\dashboard-light-browser.xml`. The contrast checks cover the
named rendered elements, not a complete accessibility certification.

## Simplified default overview

The default dashboard now prioritizes three areas: **pipeline map, selected sensor
trend and agent assessment**. One source clock and the current numerical warning
remain visible. Run settings, engineer questions, analysis progress and system
counters expand on demand. Empty comparisons are absent until requested, and full
reports open in Agents instead of duplicating the live dashboard.

The compact-overview browser check requires the primary areas to fit a
1600x1100 viewport, verifies keyboard disclosure and preserves visibly pinned
historical evidence. A separate read-only check opened the previously qualified
hosted S1 result, inspected the actual anomaly trend and reviewed the exact
original handoff and accepted critic record. Its assessment panel ended at
1090.22px in that earlier compact theme. Evidence:
`evidence\dashboard-simplified-hosted-review.json`. The
[actual dashboard screenshot](assets/engineer-dashboard-live.png) now shows the
subsequent light-theme review described above.
This did not generate new inference or change the detection/agent pipeline.
Screen-fit checks are not a human-usability study.

All **19 offline browser journeys passed**, including the new compact overview,
keyboard disclosure, on-demand comparison and original manual investigation,
grounding review, follow-up, pinned-window and mobile workflows. TypeScript and
the production UI build passed. Evidence:
`evidence\dashboard-simplified-browser.xml`. The manual replay journey now pauses
on the independent numerical warning before reviewing the scoped inspector,
rather than racing the end of an accelerated replay.

## Monitoring-first engineer dashboard

The Live workspace now puts the approved brief's Y topology beside a continuously
following pressure trend and instrument/alarm list. All 24 instrument positions
and A/B wall sides match the brief; only the supported inspection interval is
highlighted. Engineers can inspect raw measurements, compare chosen instruments
and pin immutable historical evidence without stopping numerical monitoring.
Simulated source UTC, actual admission/report UTC and historical report basis are
separate. No browser-extrapolated telemetry is displayed.

**Final offline cohort: 18/18 browser journeys passed.** This includes exact
brief geometry, delayed sensor reads during accelerated replay, atomic
map/trend/list scope, pinning an in-flight window, disconnected-clock behavior,
failure withholding, explicit unresolved triage, a 390px viewport and the existing
manual investigation/deck journeys. **16/16 monitoring integration cases passed,**
including immediate qualifying leak/instrumentation/coverage admission, persistent
ambiguity and resolved transients. Ruff, strict mypy over 38 source files,
TypeScript and the UI build passed. Evidence:
`evidence\dashboard-release-browser.xml` and
`evidence\dashboard-admission-regression.xml`.

**A fresh genuine automatic journey passed.** S1 streamed through normal APIs
while the selected pressure trend and independent numerical warning remained
usable. One automatic root used the first qualifying source window, **110s**,
and produced the reviewed **P1 200-600m** inspection handoff in **145.08s from
admission**, using seven hosted requests, all reporting `gpt-6.1-sol`. The complete
browser journey took **170.74s**, including setup, stream observation and report
review. All twelve persisted-operation checks passed on a fresh read-only audit:
collaboration, scopes, receipts, source timing, authority, bounds, critic and
attestation. No inference retry, raised timeout or weaker critic was used.
Evidence: `evidence\dashboard-release-live-browser.xml`,
`evidence\dashboard-release-live.json.gz` and
`evidence\dashboard-release-agent-operations.json`.
The [dashboard screenshot](assets/engineer-dashboard-live.png) shows this actual
preserved hosted result, not fresh inference every time the page opens.

Earlier failures remain failures:

| Hosted attempt | Observed failure | Correction |
|---|---|---|
| First | Fast hops repeatedly invalidated in-flight sensor reads, starving the chart. | Coalesce reads; retain the last complete view; commit matching map, list and trend together. |
| Second | The separate API observer disconnected with `ECONNRESET`; the live chart had passed. | At most two transport retries on idempotent observation GETs only, never inference. |
| Third | An unresolved root exhausted its budget after 222.59s; a newer useful report then took another 120.25s. The aggregate 300s observation failed. | First unresolved-only episodes gather at most one source window; actionable warnings bypass the hold. Minor NORMAL/DEGRADED changes alone no longer trigger duplicate physical reports. |

Original observation artifacts, failed browser XML and complete terminal root
audits are retained in the `dashboard-live-initial`, `dashboard-live-second` and
`dashboard-live-third` evidence files; the failure index is
`evidence\dashboard-qualification-initial.json`. Later report completion does not
relabel those failed journeys. Repeated raw projection observations are losslessly
gzip-compressed JSON; complete terminal operation audits remain readable JSON.
One successful post-fix synthetic journey is
functional qualification, **not** a reliability estimate, field response SLO,
independent prose-accuracy study or timed human-usability result.

Numerical warnings and manual inspection never wait for triage or an LLM.
The unresolved hold uses source time; the 300s task budget starts at admission.
An unresolved transient that clears needs no report; persistent ambiguity uses
the latest evidence at the review boundary. Changed physical hypotheses,
segments, material location or lost/recovered coverage still trigger review.
Accepted older reports remain visibly historical, never silently rebased.
The five-minute operator walkthrough is a design target, not a usability finding.

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
