# Subsea Integrity Copilot

Engineer decision support for subsea pipeline integrity. Existing anomaly
detectors flag pressure readings; agents help engineers investigate those alerts,
distinguish sensor faults from possible leaks, and recommend a supported inspection
interval or abstain. **Synthetic data only; not a safety system.**

The product hypothesis is reusable expert knowledge: reviewed procedures and
worked evidence help less-experienced engineers investigate at scale. Knowledge
elicitation/approval and onboarding benefit still require customer validation.
Ten minutes for manual analysis is a planning assumption, not measured labor
savings. Agent investigations have a **15-minute hard deadline**; actual hosted
latency is shown with each recording. Accelerated monitoring does not accelerate
model inference.

The global **monitoring warning** is numerical and never waits for the LLM.
It follows the latest window even when a historical investigation is pinned.
Source loss is a coverage warning, not a no-leak conclusion. A disconnected
browser labels the retained assessment as stale.

Both modes use the same map and sensor-table alert categories: **Pressure anomaly**
and **Missing value** (absent or excluded unusable readings). Pressure excursions
use a median/MAD detector fitted to verified-normal reference readings, with a
minimum scale and configured threshold. Spike, drift and paired-disagreement
screening remains available as investigation evidence, not a separate map flag
or a confirmed sensor-fault diagnosis.
The common legend contains those two raw categories. Agent-reviewed pattern
and inspection-area keys appear only when the corresponding reviewed overlays
are actually drawn. Selection and warm-up states are explained in **How to read
the map**, rather than adding more alert legend entries.

Private repository: https://github.com/ntnguyen-so/subsea-integrity-copilot.
Reviewers need repository access before the interview.

## Golden-data qualification

### Visual, S7-scale temporal evaluation

The Evaluation tab presents **ground truth and actual agent findings on two
synchronized pipeline maps**. Each of the three new recordings uses S7's
112 instruments, 56 paired stations, seven segments, 11.2 km and 360 seconds.
Cases cover a broad leak footprint, a more concentrated leak on another branch,
and a no-leak operating/shared-connection look-alike. Scattered drift, spikes,
flatlining, invalid received values and missing readings overlap the events.
Source causes and their start times are declared independently of the detector.

Choose a recording, jump to either investigation or play its timeline. Source
time pauses while recorded agent checks and handoffs unfold; measured model
wall time remains visible. An interpretation overlay appears only for its exact
accepted snapshot and input hash. Inspection overlays must also match the
production-authorized interval. Scrubbing never launches inference, and final
findings are not painted onto earlier source windows.

The temporal benchmark samples real 60-second numerical windows every 15
source seconds and schedules real agent investigations at **150 and 360 seconds**
only when pressure warnings exist. Three initial clean windows are negative
controls. This is a classification/localization benchmark, **not a measurement
of production automatic admission latency**. Both scored checkpoints, failed
roots, missed instrument labels and withheld leak intervals remain in the
denominators. Weak physical influence is continuous, so numerical flags are
displayed without inventing binary anomaly truth from detector predictions.

```powershell
. .\tools\load-environment.ps1
$env:SUBSEA_TRACE_CONTENT='1'
$env:SUBSEA_SYNTHETIC_ONLY='1'
uv run subsea spatial-evaluation --split development --seed 20261109 --output eval\results\spatial-development
# Freeze code and prompts before the measurement cohort.
uv run subsea spatial-evaluation --split held_out --seed 20261110 --output eval\results\spatial-held-out
```

The compact scorecards are backed by deterministic comparisons, not judge
opinions. Detailed metrics, original reports, exact mapping quotes and Langfuse
traces remain behind an expander. The smaller, historical reference cohorts
below do **not** qualify these larger networks or their temporal behavior.
Fresh enlarged development v7 met the predeclared 95% target: deterministic
precision/recall/F1 were 100%, localization contained 4/4 sources, and the external
explanation judge passed 6/6 reports. A separate held-out seed reproduced those
results with unchanged code/prompts and new telemetry hashes.
These small, related source families do not establish 95% field reliability.
Actual outcomes, earlier numerical-explanation failures and tracing gaps remain
in [qualification results](docs/RESULTS.md).

### First-on-call handoff

The coordinator produces a diagnosis-first assessment: leak pattern or measurement
problem, the supported inspection area, and named instrument findings. Each
conclusion explains the observed change, its paired or spatial contrast, and
why that contrast supports the diagnosis. A pressure list or a request to repeat
the available analysis is not a completed assessment.
Every pressure or instrument finding must include measured magnitudes, units,
source periods and numerical comparison readings, including secondary branches
and each named suspect instrument. Logged settings and asset IDs are not sensor
evidence. Missing comparative measurements must limit the conclusion explicitly;
neither invented numbers nor unsupported confidence percentages are acceptable.
The coordinator's claim-to-source citations are bound by application code from
the immutable ledger and successful source-read receipts, rather than asking
the model to recopy long ID lists. Unread or foreign sources remain rejected;
this binding does not approve the prose or bypass the grounding reviewer.

Location explanations connect the stronger central paired readings to their
weaker neighboring stations and the actual fit's boundary rule. Instrument
explanations distinguish one disagreeing tap or a shared-connection offset from
a pressure loss observed across independent connections. Operating changes and
weaker secondary pressure changes remain separate from unsupported leak sources.
Internal citations, run statistics, source quotes and optional follow-up questions
are retained in a collapsed audit view, not printed throughout the assessment.
The report diagnoses the supplied readings; it does not claim a physically
confirmed defect or replace site authorization.

New assisted recordings acquire up to 30 additional source seconds before
pausing for investigation, stopping earlier when independent pressure evidence
qualifies an inspection interval. Single-connection persistence alone does not
end acquisition. Historical recordings retain their original pause policy and reports.
The discovery view uses explicitly labelled final-five-second normal-reference
measurements and usable sample counts. Reports distinguish those current values
from twenty-second summaries, conditional screening statistics and historical
changes. An operating record's end time alone does not establish recovery.

The existing inspection method uses unaffected stations on either side of a
joint pressure pattern. On extended networks only, `pressure-peak-focus-v1`
can instead qualify the strongest contiguous pressure-loss focus when agreeing
pairs, complete recent observations, immediately adjacent weaker comparisons,
local independence and the unchanged 400 m width limit all hold.
Its assumptions are pinned in localization knowledge revision 2.
This is an inspection-planning priority, **not a calibrated hydraulic leak
coordinate, confidence interval or physical dispatch authorization**.
If those checks fail, the briefing gives the measured station focus and the
specific reason an interval was withheld. Independent physical pressure/flow
confirmation remains necessary before intervention; engineers should not need
to reconstruct analysis already completed by the agents.

### Historical 24-instrument deterministic agent evaluation

The **Evaluation** workspace displays labelled, recorded reference cases for
leaks on P1/P2/P3, scattered spikes, an isolated drifting instrument, invalid
readings, missing readings, mixed leak/measurement issues, and stable pressure.
Labels include the injected source's pipe and distance along it, instrument
IDs and issue types. They are evaluation truth, never runtime agent inputs.

Accuracy is **not an LLM judge's opinion**. A separate, truth-blind extractor
translates only the agents' public briefing and regional explanations into
pipeline, inspection-interval and instrument/type labels. It has the instrument
catalog, but no measurements or hidden truth. Code checks exact supporting
quotations, known IDs, schema and duplicate labels, then computes precision,
recall, F1 and localization containment against the declared source labels.
Healthy comparison partners must not be mapped as faulty. Missing readings
remain unknown rather than normal pressure or confirmed hardware failure.

The extractor is calibrated against joint pressure anomalies without instrument
faults, coexistence, negation/healthy-partner and deliberately incorrect-confirmation
controls. It must faithfully map a wrong
answer, not repair it before grading. Original answers, mappings and quotations
are visible for human audit: quote membership alone cannot prove semantic
correctness. A **separate** external judge grades explanation grounding and
readability, with adequate and incorrect/injection controls. The default agent
is `gpt-6.1-sol`; extractor/judge is `gpt-6.1-terra`, verified available through
the same owned CLI transport. Requested and observed identities are retained.
Different models are not proof of independence.

```powershell
. .\tools\load-environment.ps1
$env:SUBSEA_TRACE_CONTENT='1'
$env:SUBSEA_SYNTHETIC_ONLY='1'
uv run subsea reference-evaluation --split development --seed 20261107 --output eval\results\reference-development
# Freeze prompts after development; do not tune on this measurement seed.
uv run subsea reference-evaluation --split held_out --seed 20261108 --output eval\results\reference-held-out
```

Each command freezes eight content-addressed datasets before inference and uses
the production sliding-window monitor, pressure-only automatic admission and
three persisted agents. It does not submit prewritten specialist answers.
Each case gets one initial root; internal repairs remain actual recorded calls.
No output directory can be reused. Failed roots, failed extractions, no reports
and withheld leak intervals remain in the appropriate denominators. Missing-only
and stable controls are scored for zero automatic agent invocations, not counted
as successful agent answers. Agent and numerical detector metrics are separate.

The implementation hashes all package Python files and agent prompts before
execution and verifies that they remain unchanged. Diagnosis intake supplies
original normal-pressure summaries for priority and quiet instruments; on extended
networks it reads all 112 instruments in bounded, losslessly encoded batches.
An audited, role-authorized search supplies relevant operating and calibration
record candidates; the agents must still open and check the original records.
The coordinator may cite original evidence only after
an audited read, and the reviewer receives those same source bodies. Invalid
read arguments are recorded and can be corrected within the existing budgets;
foreign scope, role violations and operating actions still fail closed.

The dashboard reads `runtime\evaluation-report.json` without inference; each
cohort's receipt and audits remain under its output directory. Langfuse records
agent tool/model work, the truth-blind extractor packet/output and the separate
judge packet/verdict. Trace IDs and content hashes link the records.

**Strictly over 95% is a reference qualification target, not a promised result.**
The dashboard shows denominators, failures and Wilson intervals, including
unmeasurable rates. Held-out seeds vary noise within the same known pattern
families. This small, original 24-instrument topology cohort neither validates
field hydraulics nor establishes 95% reliability on arbitrary S7 windows.
Inspection containment is bounded to an agent-proposed interval of at most
400 m; midpoint error is not an exact leak-point prediction.

The frozen held-out cohort (seed `20261108`) achieved **100% precision, recall
and F1** for leak recognition, affected pipelines, instrumentation concerns,
suspect instruments and issue types. All four leak sources were contained in
agent-proposed inspection intervals; all six pressure-triggered reports passed
the separate explanation judge. Stable and missing-only controls invoked no
agents. This is one eight-case reference cohort, not field certification.
The [recorded results](docs/RESULTS.md) retain the three failed development
cohorts, the qualified development cohort and the untouched held-out result.
The [historical held-out receipt](docs/evidence/reference-held-out-20261108.json)
is retained separately. The committed
[latest enlarged evaluation receipt](docs/evidence/evaluation-report.json)
serves as the read-only dashboard fallback on a clean clone, including its
unmet targets and failed roots.

Versioned synthetic cases and hidden evaluation labels live in
`fixtures\golden\cases-v1.json`; the judge rubric is
`fixtures\golden\judge-rubric-v1.json`. Qualification tests coordinated leak
patterns, scattered instrument problems and mixed evidence, plus a missing-only
negative control. Truth labels are evaluation inputs, not agent inputs.

After starting the required services and loading the external credentials:

```powershell
$env:SUBSEA_TRACE_CONTENT='1'
$env:SUBSEA_SYNTHETIC_ONLY='1'
uv run subsea golden --stage qualify --mode live --output eval\results\golden-live
```

This spends real hosted inference calls. It evaluates fresh, tenant-isolated
agent runs, checks classification/localization against the synthetic truth, and
uses a calibrated LLM judge for explanation, evidence and uncertainty quality.
Stored Langfuse observation trees and exact judge input/output hashes must
verify; successful exporter delivery alone is insufficient. Frozen source hashes
bind saved runs to their original measurements.

These small golden cases and a same-model judge are regression evidence, not
independent field validation or a measured accuracy/labor-saving claim.

### Open the actual qualified recordings

```powershell
. .\tools\load-environment.ps1
uv run subsea serve-recorded --tenant golden-eval-1aae671f78ef --port 8087
```

Open http://127.0.0.1:8087 with the same local operator credentials. This isolated
console disables ingestion/agent workers and rejects execution commands; it
does not copy records into the main tenant or rerun models. Choose a saved
**Recorded pressure sample** and scroll to the investigation panel.
The tenant and sample suffixes below belong to the retained local qualification.
After running a new qualification, use its returned tenant ID and replay IDs.

| Case / sample suffix | Intended pattern | Selected hosted result |
|---|---|---|
| G1 / `4b21dfb2` | Coordinated pressure footprint | Possible leak; P1 200-600 m inspection bracket |
| G2 / `af5af2e6` | Scattered spikes and missing readings | Instrument/telemetry concerns; no inspection interval |
| G3 / `49b8da58` | Leak footprint mixed with quality problems | Possible leak plus quality concerns; P1 200-600 m bracket |
| G4 / `98d4150d` | Missing values without pressure anomalies | Zero automatic agents |

The selected substantive runs took **175-266 seconds**. One initial G3 attempt
failed and four judge attempts were rejected; their history is retained.
Selected coverage passes are not an all-attempt success rate. See
`docs\RESULTS.md` for the evaluation and trace receipts.

## Run on Windows

Requires Python 3.11, `uv`, Node.js, Docker Desktop with Linux containers, and
PowerShell. Agent-assisted runs additionally require an authenticated GitHub
Copilot CLI with model access. Internal scripted API/CLI fixtures work without
inference and remain labeled; they are not a customer-facing workflow choice or
evidence of live-model performance.

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

The **investigation panel** separates detector output from actual agent
work. New assisted runs show pressure alerts immediately, then collect context
until measured persistence is sufficient or at most 20 additional source seconds
have elapsed. They **pause simulated ingestion on that evidence-ready window**
and wait for fresh agents. Existing recordings retain their original pause policy.
Missing
values, exclusions and quality-only concerns never launch automatic agents by
themselves; they remain visible warnings and investigation evidence. The panel
shows the Sensor Quality Agent, Event Diagnosis Agent, Response Coordinator and
the coordinator's separate Grounding Reviewer pass,
actual model/tool counts and executed public activity, not invented percentages.
Scroll to the panel for their
handoffs, executed record searches/comparisons, source quotes, reviewer outcome
and engineer verification question. These findings load automatically on Live;
opening the Agents tab or asking a question is not required.

### What each agent does

| Visible role | Operator question it addresses |
|---|---|
| Sensor Quality Agent | Which readings can we trust, and which need caution? |
| Event Diagnosis Agent | Do nearby instruments change together like a possible leak, or do the anomalies better fit instrumentation, communications or operating changes? |
| Response Coordinator | What should an engineer check next, and is an inspection area supported? |
| Grounding Reviewer | Does the proposed response actually follow from the cited evidence? |

There are **three persisted agent roles**. The reviewer is a separate model call
within the coordinator task, not a fourth independently scheduled specialist.
The coordinator assigns specialist checks; quality findings inform diagnosis;
the coordinator drafts the response; the reviewer checks it before release.

The public work journal shows actual requested checks, observations, agent-written
questions, provisional drafts, reviewer feedback and linked handoffs. It labels
application-required intake separately from model-requested investigation.
Drafts are not accepted findings and cannot release map overlays. Saved runs
restore their persisted journal; older recordings without this history say so.
These are public explanations and evidence, **not private model chain-of-thought**.

Hosted engineering briefings lead with a supported review priority, then explain
the measured pattern, competing explanations and useful next checks in calm,
plain language. They normally use 250-450 words in short, separated paragraphs,
with technical terms explained where needed. The main answer can use up to
6,000 characters; causal and regional explanations up to 2,400 each. Grounding
still checks every assertion in each complete cited explanation, including its
later paragraphs, with up to sixteen exact-source anchors. Confidence in a review
priority is not a claim of confirmed leakage, field calibration or operating
authority. Existing recordings retain their original wording.

The shared map initially shows only pressure anomalies and missing values. Pattern and
inspection overlays require an accepted agent handoff matching the displayed
window, evidence hash and versions. A numerical candidate alone is not displayed
as an agent result. Pending, failed, unavailable, mismatched and historical
work records do not become current investigations. SCRIPTED recordings remain offline
fixtures, not evidence of hosted performance.
Opening a recorded run loads its saved actual report; it does not rerun inference.
Older continuous runs retain their stored playback policy and original behavior.
An immutable evidence snapshot is the input to an agent, not a prewritten answer.

Choose between exactly two customer workflows under **Workflow / new run**:

Both keep the **same interface**: map, trends, sensor descriptions/order,
legends, comparison defaults, tabs, questions, raw/canonical evidence, coverage
metrics and detector warnings. The investigation workspace stays visible when
execution is off; it does not claim an agent ran. Manual question submission
is rejected explicitly in that mode without making an LLM call.

- **Sensor alerts only:** the map and list flag individual instruments. Engineers
  examine histories one by one and connect timing/location manually. There is no
  combined leak/fault assessment, inspection interval, agent task or LLM call.
- **Agent-assisted investigation:** the product correlates the alerts, distinguishes
  possible leaks from sensor/telemetry concerns or insufficient evidence, and
  recommends a supported inspection interval when justified. Real hosted agents
  investigate records and explain competing causes with a reviewed evidence packet.

Start S1 in **Sensor alerts only**, then start it again in **Agent-assisted
investigation**, keeping the same scenario, seed and source time. This compares
the same sensor data, not two inference adapters. The alert-only workflow is an
illustration of the prospect's assumed current process, not a measured customer
installation. A strong fixed workflow is a separate, credible comparator.
Changing settings applies to the next run; existing runs retain their workflow.

The default view has three areas: **pipeline map, sensor trend and agent
assessment**. Source time and the current warning stay visible. Run settings,
engineer questions, detection criteria and system diagnostics expand only when
needed. Comparisons appear after selecting them; full reports open in Agents,
not as a second answer beneath the live dashboard.

The light theme uses matching map and chart meanings: **amber** marks individual
pressure anomalies, a **blue ring**
selects the graphed instrument, and grey-filled markers are **not assessed**.
Dashed sensor outlines show missing/excluded readings; amber diamonds show
agent-reviewed pressure patterns only after a matching report. These flags can coexist and are not confirmed leak or
hardware-failure diagnoses. Chart keys separately identify pressure, baseline
thresholds and missing-data bands; map, table and trend retain the same window.
Both workflows show the **same raw pressure and missing-value symbols**.
These inexpensive detector flags can appear before any LLM call.

1. Choose **S1**, select **Agent-assisted investigation**, then **Start new run**.
   This uses real hosted inference; no scripted/live selector is exposed.
   Select 10x speed and Play. The continuously updated UTC clock comes from the
   server, never browser-extrapolated measurements. Samples arrive every simulated
   second; 60s windows slide every 5s after the 5s lateness allowance.
2. Select a station on the map or an instrument in the alarm list. Its pressure
   trend continues following received windows. Inspect threshold crossings, gaps
   and paired instruments just as in a manual investigation. Check up to four
   instruments for a custom same-window comparison. During fast replay or slow
   reads, the map, alarm list and trend advance together only after scoped
   observations arrive; the last complete view stays visible instead of flashing
   blank or mixing windows. The latest numerical warning remains independent.
3. After warm-up, a newly raised pressure anomaly pauses the source and immediately
   queues fresh specialists. Missing/excluded readings and quality-only flags
   never trigger an automatic investigation by themselves. Agents still examine
   them when investigating pressure anomalies. The first alert may be an instrumentation issue;
   agents must abstain if a leak pattern has not developed. Play and Step are
   server-locked during the checks, including at 10x. Repeated persistent flags
   do not cause identical investigations. No specialist from another root is
   reused for these automatic investigations. The input window and source clock
   stay fixed while actual model requests and tools execute.
4. After the reviewed report is recorded, the source **remains paused**. Review
   the findings, then explicitly **Continue monitoring**. Provider/knowledge/budget
   admission failures remain visible; **Continue without report** never clears a
   detector alert or implies a successful analysis. Existing dispatch budgets
   still apply. Only synthetic simulation pauses: a production safety feed must
   continue independently of the LLM.
   **Compare with existing workflow**
   opens a same-alert comparison of individual alerts/manual work versus the
   product's actual document reads, measured comparisons, competing explanations,
   grounding review and handoff. Both columns use the report's original snapshot,
   not a newer live window. Hosted processing time is measured; ten-minute manual
   investigation is only an assumption, and human review is additional.
   Review the report and its original
   evidence. Historical reports are labeled, never silently rebased. Failures
   withhold reports without clearing numerical warnings. Recorded continuous
   workflows retain their original material-change dispatch and bounded context
   gathering; start a new run to use anomaly-paused monitoring.
5. Open raw records, compare histories or ask a question to **pin** an immutable
   window. Pinning the inspector does not itself pause ingestion; **Follow current**
   returns to the current source window. An automatic investigation hold does
   pause the simulated source. Detection criteria and provenance remain in the
   expandable details, and full agent receipts remain in Agents.

The three suggested questions are "Leak or faulty sensors?", "Where should we
inspect, and why?", and "What evidence supports this, and what remains unknown?"
This is a five-minute handover design, not a measured human-usability result.
The 900s report budget starts at admission. Source-time triage, wall-clock queue
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

### Larger manual-investigation workload: S7

S7 is a separate **11.2 km, seven-segment network with 56 paired stations and
112 pressure instruments**; S1-S6 retain the brief's original Y and their
existing qualification cohort. At source +90s, a pressure footprint with a
disruptive near-source core and weaker connected responses coincides with
scattered drift, staggered spikes, gaps, flatlines and invalid readings, a shared
gateway offset, and a positive operating-pressure transition on another branch.
Operating records also contain superseded and unapproved material.

Run S7 in each customer workflow with the same seed. In **Sensor alerts only**,
inspect individual histories and compare up to four instruments across branches.
**Map focus** zooms a branch to readable station labels; the alarm table keeps
the whole network available, and selecting a different branch's instrument
updates the map focus. The overview still represents every instrument.
Network length, instrument count and actual current-window flags are displayed,
without inventing a manual investigation duration.

The numerical screening result and any qualified inspection interval are shown
separately from **agent-authored regional causal assessments**. Agents can retain
several competing causes or an unresolved pattern even when the numerical fit
withholds a location. The wider S7 footprint can legitimately produce an
ambiguous or withheld interval; it must not be forced into the earlier bracket.

The diagnosis agent receives a compact measurement table for **all 112
instruments**, including weak and quiet channels. It chooses up to 24
instruments per joint before/after comparison: pressure profiles, actual usable
sample overlap, paired correlations, graph distances, extrema and adjacent
steps. Missing data are never imputed into physical evidence. These are
measurements, not a causal classifier or pressure-wave localization model.
Review remains bounded and partial, not an exhaustive expert assessment.
Discovery magnitudes use the same explicitly timed final 20-second usable
median against verified-normal baseline for every instrument, with sample
counts; they do not mix threshold-conditioned and whole-window summaries.

### Capturing and applying expert knowledge

`fixtures\knowledge\pressure-investigation.json` stores versioned natural-language
guidance, prerequisites, verification steps, counterexamples and limitations.
The investigation-program card expresses a reusable procedure; the other cards
express domain heuristics. This follows DANA's capture/apply distinction, **not**
a claim of DanaOS/OpenSSA implementation. The current corpus is research-curated
with advisory authority, **not approved by a pipeline SME**.

The service selects cards by site, pack, role, status and validity; withholds
declared conflicts; pins a full immutable packet to the root and every child;
and checks knowledge-plus-case citations in the final report. Selection uses
actual processing time, separately from historical incident timestamps.
Undeclared semantic contradictions still require human curation. The response
view shows guidance excerpts; the full selected packet and provenance remain
available in the casefile.

**Why these checks** links actual recorded knowledge IDs and discriminating
questions to executed history calls. Regional conclusions must cite real
comparisons and applicable guidance; knowledge is not an observation or
authority to confirm a leak. The separately prompted same-model critic checks
grounding, not physical correctness or expert approval.

Inspect the packet with `uv run subsea knowledge`. Run the paired synthetic
ablation with `uv run subsea evaluate --suite knowledge --mode scripted`
(contract checks) or `--mode live` (hosted inference, consumes quota).
Matching input hashes and accepted contracts do not prove incremental knowledge
benefit; see `docs\RESULTS.md`, including failed hosted attempts.
`uv run python tools\qualify-joint-timing.py` runs two additional hosted
counterexamples with identical individual before/after distributions but changed
cross-sensor timing. It records full explanations for independent semantic
review, not an automatic accuracy grade.

Execution allowances are now **3x the previous limits**, including database
enforcement. Each root allows 900 seconds, 30 model calls and 54 tool calls;
the provider prompt allows 144,000 characters, individual model requests 180
seconds, and worker leases 1,080 seconds. Quality allows 9 model/15 tool calls;
diagnosis 12/24; the coordinator 9/15, or 18 model calls for its reviewed
engineering-response protocol. The shared root ceiling still applies.
Three schema repairs and three grounding corrections are allowed, with a final
review after the third correction; unsupported responses still fail closed.
Admission allows 48 queued roots, 300 generation model calls, 18 automatic
roots per generation, 9 per episode and 9 manual roots per operator/minute.
Automatic admission permits three times the prior rate (20-second cooldown).
CLI qualification permits 27 manual roots and 3 standalone baselines.
Joint comparison handoffs use lossless
columnar encoding and a 48 KiB tool-result bound. Repeated claim values reference
their identical evidence value without removing source data. Diagnosis delivery
also has a cumulative 63 Ki-character normalized-JSON budget; additional reads
fail explicitly with `context_budget_exceeded`, which must remain a report
limitation. No numerical certainty or operating authority is increased.
Schema repair regenerates from the same complete source messages and validator
feedback; the rejected draft remains audited but is not replayed into the repair
prompt. Knowledge packets allow 24 cards/72 KB; health pages 24 instruments;
history reads 9 records and comparison ranges 900 seconds. Model output/capture
and trace-content ceilings are also tripled. Raw source evidence is never
discarded to make a report fit. Existing recordings retain their original
deadlines and outcomes; the larger allowances apply to fresh work.
The [fresh budget qualification](docs/evidence/product-budget-qualification.json)
records a same-input hosted G3 investigation: 9 model calls, 17 tools, 273.969
seconds and a reviewed P1 200-600m inspection interval. Diagnosis used 9 tools,
crossing its former 8-tool ceiling; the three named-agent Langfuse trees were
checked in stored observations. This is a focused regression, not field certification.

The latest automatic S7 first-call briefing completed in **743.875 seconds**.
It scopes P5 integrity review to **600-1000 m**, separates P7's shared-connection
offset from P2's operating rise and individual spike, and gives immediate
read-only priorities without asking the engineer to repeat available analysis.
The [complete accepted briefing](docs/evidence/s7-first-call-briefing.json) and
[qualification results](docs/RESULTS.md) preserve the outcome and earlier failures.
Its 12.4-minute inference latency is a material workflow limitation; recorded
playback is available for a time-limited meeting.
One accepted run is not a reliability, field-accuracy or labor-saving result.

This workload contains **one physical leak**, not simultaneous multi-leak
localization. The pressure footprint is synthetic, not a hydraulic simulator.
More sensors demonstrate review complexity; they do not prove labor savings,
field accuracy or superiority over a well-designed deterministic workflow.

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

Stop the monitoring server and finish any qualification cohorts before Python integration
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
900s for new runs from question admission to accepted result; UI/human receipt is a separate
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

The deck follows the pressure-monitoring workflow and the brief's three questions.
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
