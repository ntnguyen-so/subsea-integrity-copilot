# Agent operations evaluation

## Measured result: first attempts and explicit retries

The genuine hosted cohort completed all **18 planned attempts**. **15/18**
produced rubric-correct, reviewed reports within 300s; the other three failed
closed. The matched quality-aware fixed workflow produced **18/18** rubric-correct
reports and was faster on all 15 pairs where both completed correctly.
**The claim "same accuracy, agents are faster than rules" is not supported.**

| Measure | Hosted agents, first attempts | Quality-aware fixed reports |
|---|---:|---:|
| Correct structured report and timely delivery | 15/18 | 18/18 |
| All-attempt report p50 | 129.42s | 0.562s |
| All-attempt report p95 | 170.03s | 0.881s |
| Longest attempt | 186.64s | 0.901s |
| Fresh model-call attempts | 112 | 0 |
| Calls with observed model identity | 109, all `gpt-6.1-sol` | 0 |
| Reports revised and accepted after criticism | 5 | No model-written prose |
| Failed attempts that withheld the report | 3/3 | No failed attempt |

This is **report delivery reliability plus a structured correctness rubric**,
not independent accuracy adjudication of every generated sentence. All 15
accepted reports passed the rubric; failed reports remain in the denominator.
The numerical detector is shared, so this is not a better leak-detector claim.

The full cohort's qualification gate remains **`passed:false`** in
[`evidence/agent-operations-live.json`](evidence/agent-operations-live.json).
On the user's explicit retry request, all three failed case identities were
rerun with new roots: **3/3 passed in 118.79-125.77s**, with 19 observed
`gpt-6.1-sol` requests. See
[`evidence/agent-operations-live-retry.json`](evidence/agent-operations-live-retry.json).
That file links each new root to its original failed root. It does not replace
the first-attempt result or turn it into 18/18 reliability. Across both runs,
there are **18 accepted reports in 21 attempts**. Retry processing times do not
include the wait before a manual retry and cannot establish five-minute recovery
from the original admission.

### Per-case evidence

| Case | First-attempt state | Agent seconds | Fixed seconds | Fresh model calls | Critic outcome |
|---|---|---:|---:|---:|---|
| S1/Q1 | SUCCEEDED | 131.42 | 0.553 | 7 | Accept |
| S1/Q2 | SUCCEEDED | 131.66 | 0.803 | 7 | Accept |
| S1/Q3 | SUCCEEDED | 76.50 | 0.768 | 3 | Accept |
| S2/Q1 | SUCCEEDED | 134.80 | 0.585 | 7 | Accept |
| S2/Q2 | SUCCEEDED | 141.51 | 0.832 | 7 | Accept |
| S2/Q3 | SUCCEEDED | 76.94 | 0.571 | 3 | Accept |
| S3/Q1 | ABSTAINED | 160.68 | 0.381 | 8 | Accept |
| S3/Q2 | FAILED | 91.05 | 0.231 | 6 | Not completed |
| S3/Q3 | ABSTAINED | 121.26 | 0.427 | 5 | Revise, accept |
| S4/Q1 | ABSTAINED | 167.09 | 0.828 | 8 | Accept |
| S4/Q2 | ABSTAINED | 121.64 | 0.901 | 7 | Accept |
| S4/Q3 | ABSTAINED | 127.43 | 0.877 | 5 | Revise, accept |
| S5/Q1 | ABSTAINED | 163.52 | 0.401 | 9 | Revise, accept |
| S5/Q2 | ABSTAINED | 186.64 | 0.436 | 10 | Revise, accept |
| S5/Q3 | ABSTAINED | 109.05 | 0.292 | 5 | Revise, accept |
| S6/Q1 | SUCCEEDED | 122.45 | 0.456 | 7 | Accept |
| S6/Q2 | FAILED | 148.08 | 0.474 | 7 | Not completed |
| S6/Q3 | FAILED | 61.03 | 0.783 | 1 | Not completed |

S3/Q2 failed because `shutil.rmtree` raised `PermissionError` in the CLI
transport's `finally` block. That cleanup could mask a result or the primary
provider exception and discard useful metadata. The transport now retries only
local cleanup, at most four times and within the existing deadline. It does
**not** retry inference. Persistent cleanup failure is categorized, sanitized and
fail-closed; an existing authentication/quota error is preserved so provider
blocking still works. Forced transient/persistent lock regressions verify these
paths. All 19 requests in the genuine retry cohort cleaned up on their first
attempt; that run does not itself reproduce a transient directory lock.

S6/Q2 and Q3 hit the existing 60s per-call provider deadline. The limit was not
raised to obtain a pass. Their explicit fresh retries succeeded; provider
timeouts remain an operational risk, not a bug claimed to have been eliminated.

### What the operation audit actually found

| Operation group | First cohort | Interpretation |
|---|---:|---|
| Role authority, pinned arguments, source-time visibility | 18/18 each | No recorded scope/authority breach |
| Resource bounds, receipt accounting, scoped reuse and idempotence | 18/18 each | Failed attempts also retained their limits/counters |
| Specialist collaboration and observe-before-follow-up | 17/18 each | S6/Q3 timed out before specialist investigation |
| Accepted-result revalidation, critic sequence and final review attestation | 15/18 each | Three failed attempts cannot count as completed reviews |
| Failure withholding | 3/3 actual failures | No unchecked report was released |

All 13 operation checks passed on each of the 15 accepted reports, and on all
three explicit retries. The first run contains **192 unique executed tool
receipts**: 154 application-required intake reads and 38 model-requested history
actions, with zero recorded tool-read errors. The model deserves credit for the
38 actual history choices, not the 154 mandatory reads.

Five first-run questions reused two previously accepted specialists. Their
all-attempt p50 was 109.05s, versus 134.80s for the thirteen non-reusing roots;
these are different tasks, not randomized proof that reuse caused the difference.
Reused work's earlier inference remains separately attributed.

The critic genuinely changed reports, not merely acknowledged them. Examples:
S4/Q3 over-described acknowledged valve commands as verified execution; S5
answers changed possible source omissions into definite omissions; a retry's S6
answer used references that did not support its sensor-health assertion.
Other criticism was conservative verification/citation feedback.
**Five revisions are not five independently confirmed hallucinations prevented.**
The revised text, paragraph findings and exact source quotes are retained.

The pre-fix full regression passed **265 tests**. After the transport fix,
**45 targeted tests** passed, including forced transient/persistent cleanup
locks, preservation of provider authentication errors, bounded deadlines and
operation-rubric failure accounting. No test result substitutes for the genuine
first-attempt failures. The offline 18-case cohort passed all contract checks
and used zero hosted requests.

The retained `agent-operations-scripted-initial.json` failed because the new
evaluator initially looked for lowercase limitation tokens instead of the
actual `SYNTHETIC_UNCALIBRATED` claim and application-rendered `READ ONLY`
disclosure. Its initial hosted-call label also counted scripted turns.
Those are evaluator defects, not agent hallucinations. They were corrected
before the hosted cohort; the raw failed artifact was not rewritten.

## What this evaluates

The unit is a **completed engineer investigation**, not an anomaly flag, model
call or a plausible-looking answer. Two methods receive the same immutable
numerical snapshot, arrival-gated observations and incident-time history corpus:

1. **Quality-aware fixed workflow:** broad ranked search, read the first three
   admissible records, compare quality-flagged instruments spread across the
   network, validate contextual support, then render a conservative report template.
   It executes real scoped database reads and comparisons with **zero LLM calls**.
   It does not read an agent answer, scenario truth or evaluation expectations.
2. **Production agent workflow:** question planning, sensor-quality specialist,
   diagnosis specialist, bounded history investigation, operator interpretation,
   separate-context critic, at most one revision and fresh review. Actual
   PostgreSQL tasks, tool/model receipts and review attestations are audited.

The fixed workflow is intentionally credible, not an intentionally weak
"one anomalous sensor means leak" straw man. A deterministic template can already
explain a known, repetitive workflow. An agent must earn its extra latency and
cost through useful question-specific interpretation or adaptability; this
benchmark must not assume that it does.

## Frozen cohort and scoring

The current cohort is **six scenarios x three customer questions x one seed
(91000) = 18 planned reports**. Every scenario uses its mature `[120,180)` window
at source clock 185s. Raw arrival filtering precedes normalization, preventing
later conflicting records from changing an earlier fixture.

| Scenario | Expected numerical decision | Context expectation | Important record |
|---|---|---|---|
| S1 nearby pressure drops and separate sensor fault | Suspected leak; P1 inspection 200-600m if requested | Unresolved operating context | Incomplete operating-log coverage |
| S2 scattered drift, spikes and gaps | Sensor/telemetry issue | Instrumentation context, not proven hardware failure | At least one relevant approved maintenance record |
| S3 source outage | Insufficient evidence; no location | Unresolved | Source-coverage limits |
| S4 broad operating pressure change | Insufficient evidence; no localized leak | Operating change plausible, not causal clearance | Actual valve-command record |
| S5 leak hidden by coverage loss | Insufficient evidence; no location | Unresolved or telemetry-maintenance context | Incomplete telemetry restoration |
| S6 normal variability | No event supported; not a safety conclusion | Unresolved historical cause | Source-coverage limits |

Questions are the three in the customer brief: classification, inspection
rationale, and evidence/unknowns. The same programmatic report rubric checks
completion, physical decision, interval/withholding, contextual assessment,
appropriate next action, cited-source authority, relevant history actually read,
measured comparison, coverage disclosure and limitations.

Expected labels, record groups and permissible next actions are exported in the
raw report. They are evaluation-only and never supplied to either method.
S5's correct abstention is **not** counted as detection of its hidden leak.
Inspection interval containment and the numerical detector's all-leak recall
remain separate measures in `RESULTS.md`.

**"Rubric-correct" is deliberately narrower than "every prose assertion is
correct."** Generated explanations, competing causes and follow-up questions
remain attached for review. The same-model critic is a production control,
not an independent gold-standard semantic grader. Independent expert prose
accuracy, engineer effort and monetary cost remain explicitly null.

## Evaluating the operations themselves

For each real root, the audit follows fresh and reused dependency closures and
checks the following against actual persisted records:

| Operation | Measured check |
|---|---|
| Planning and delegation | Quality feeds exactly one linked diagnosis; root consumes linked specialist results |
| Collaboration | Accepted specialist outputs revalidate against their original tool receipts; limitations and abstention propagate |
| Tool choice | Full actual names, arguments, results and errors retained; model-selected history actions separated from application-required intake |
| Think/observe/act discipline | Search precedes follow-up reads/comparisons; each history receipt binds the pinned corpus |
| Retrieval | Relevant records actually opened; citations resolve to read current records; no future authored/available/effective source enters |
| Measurement use | Report links an executed pressure comparison rather than inventing measurements |
| Scope and reuse | Exact tenant/site/generation/snapshot/mode/corpus compatibility and persisted reuse bindings |
| Criticism/reflection | Actual critic model phase; revision requires reflection and second critic phases; final accepted attestation revalidated |
| Resource accounting | Reserved counters match recorded model/tool calls; inherited earlier work is not counted as new inference |
| Bounds/authority | Per-role budgets, ten-model/eighteen-tool/two-child root limits, pinned tool arguments and read-only registry |
| Idempotence | Resubmitting the exact request returns the same task and changes no model/tool counters |

The audit does **not** attribute mandatory intake reads to LLM autonomy. It
reconstructs their deterministic call identities from the production algorithm;
history searches/reads/comparisons are model-requested actions. Reused specialists
are shown with original IDs and prior call counts. Repeated read-only receipt
inspection is evaluation overhead, not hidden model inference.

Successful tasks are not counted as successful failure-injection tests.
Withholding is measured only when a failed task actually occurs. Separate
production-path regression tests exercise second rejection, future/stale sources,
wrong-sensor maintenance support, future-arrival contamination, fabricated
context, immutable checked fields, missing/tampered review binding, durable
checkpoint reopening and exact-source handoff. JUnit evidence is
`evidence/agent-operations-regression.xml`; SCRIPTED exercises workflow contracts,
not genuine semantic judgment.

Concrete negative/recovery checks in that recorded run include:

| Fault or recovery operation | Executed regression |
|---|---|
| Unauthorized tool/snapshot and duplicated dispatch | `test_gateway_scope_authority_and_idempotent_receipt` |
| Restart after exhausting the root budget | `test_exhausted_root_budget_is_not_reset_by_new_service` |
| Durable provider quota failure; no automatic retry | `test_provider_quota_is_durable_unavailability_without_retry` |
| Replay checkpoint without dispatching tools twice | `test_checkpoint_tool_interrupt_replays_receipts_without_dispatch_twice` |
| Future source and wrong-tenant retrieval | `test_future_documents_and_other_tenants_never_enter_retrieval` |
| Stale citations, invented context and future comparison | `test_stale_citations_fabricated_context_and_future_comparisons_are_rejected` |
| Late conflicts cannot rewrite a pinned comparison | `test_future_arrivals_cannot_change_a_pinned_pressure_comparison` |
| Six distinct review-attestation mutations | `test_current_reports_require_exact_complete_grounding_attestation[...]` |
| Second critic rejection withholds the report | `test_uncertain_critic_withholds_report_after_one_revision` |
| Critic checkpoint recovery adds no new inference | `test_grounding_checkpoint_reopens_without_new_model_calls` |
| Reflection cannot rewrite checked conclusions | `test_reflection_cannot_rewrite_checked_physical_or_history_findings` |
| Actual persisted revision success and repeat-fabrication failure | `test_fabricated_assertion_is_revised_and_reviewed_with_persisted_budget[True/False]` |
| Monitoring progresses during provider outage | `test_outage_windows_progress_when_provider_is_unavailable[...]` |
| Fenced SQL leases, call reservations and child lineage | `test_fenced_leases_children_and_call_receipts` |

These are controlled tests of application operations, not failure-rate estimates
from real customer traffic. Provider-error injection does not mean deliberately
exhausting a hosted quota.

The retained genuine seven-case critic challenge separately accepted its
grounded control and rejected all six injected unsafe/unsupported answer
assertions. A previous genuine full-workflow injection and a naturally generated
overclaim also exercised author revision and fresh review. These are separately
labeled in `RESULTS.md`, not silently added to this cohort's denominator.

## Latency and failure accounting

Both report clocks start after the shared numerical snapshot is ready. Agent
wall time includes submission, planning, specialist execution, inference, tool
actions, criticism and any reflection/re-review. Fixed wall time includes actual
retrieval/comparison and template rendering. Audit and scoring time are excluded
from both. The fixed method runs first in each matched pair.

The first question per scenario/seed has no compatible specialists. Later
questions may reuse them; raw evidence identifies reuse. Cold and warm samples
must not be treated as identical workloads. Both methods run locally,
sequentially with one active qualification root; this is not a concurrency,
availability or production-scale SLO experiment.

Every planned case stays in the denominator. The artifact records an attempt
before execution, persists each finished row immediately, refuses to overwrite an
existing output and retains errors. Interrupted attempts are distinguished from
not-attempted cases. Failed reports are not discarded from timing samples;
"correct within 300s" requires both report correctness and timely delivery.
The output includes all-attempt p50/p95/max, not merely successful-call averages.
Small-sample percentiles are descriptive, not a population guarantee.

The numerical warning has a different onset-to-warning clock and never waits
for this report workflow. Human review/acknowledgement is another clock and is
unmeasured. The proposed ten-minute manual analysis baseline is an assumption:
subtracting agent latency from 600s does **not** establish measured labor savings.

## Reproduce

Stop other qualification runs and finish any schema-reapplying tests before
starting a cohort. Load the owned environment in the new PowerShell process:

```powershell
. .\tools\load-environment.ps1
uv run pytest -q --junitxml=docs\evidence\agent-operations-regression.xml
uv run python scripts\evaluate-agent-operations.py --mode scripted `
  --output runtime\agent-operations-scripted-new.json
uv run python scripts\evaluate-agent-operations.py --mode live `
  --seeds 91000 --output runtime\agent-operations-live-new.json
# Explicitly retry only failed cases in a separate artifact:
uv run python scripts\evaluate-agent-operations.py --mode live `
  --retry-from runtime\agent-operations-live-new.json `
  --output runtime\agent-operations-live-retry-new.json
```

LIVE consumes hosted Copilot allowance and pins `gpt-6.1-sol`. Source data,
rubric, protocol, all actual action receipts, role/model phases, candidate reviews,
complete reports, baseline outputs and timing are in the output JSON. Provider
authentication/quota failure stops further hosted work without switching models
or silently retrying failed cases.

## Buying decision

"Same accuracy, faster" would be persuasive **only for matched end-to-end tasks
and measured clocks**. A rules-generated report is likely faster than hosted
inference; a raw rules alert plus a human investigation is a different workflow.
This evaluation tests the first comparison directly. Demonstrating a time saving
over the second requires a timed engineer study with equivalent evidence,
quality requirements and review steps.

To establish that commercial claim, have engineers complete counterbalanced,
blinded tasks using fixed reports versus the agent workspace. Include review and
correction time, score both against approved outcomes, retain failed/missed cases,
and compare total time at equal quality. No such human study has been run here.
