# Qualification results

All measurements below are **synthetic demo evidence**, not field reliability.
The private repository is owned by `ntnguyen-so`; no employer data, reference deck,
thesis PDF, credentials or copied marketing artwork is included.

| Gate | Evidence/status |
|---|---|
| Python regressions | 167 tests passed against the independently owned PostgreSQL environment. |
| Static checks | Ruff, strict mypy over 27 source files, TypeScript typecheck and esbuild passed. |
| Dependencies | Installed public package versions audited; no known vulnerabilities reported. Not a security certification. |
| Numerical hold-out | 120 mature windows, 20 seeds x six scenarios; frozen report in `fixtures\synthetic\evaluation-results.json`. |
| Scripted PostgreSQL agents | 27/27 accepted-correct answers; real durable graph, checked claims and baseline, not real inference. |
| Actual stored observability | Scripted cohort's agent/generation/tool/guardrail tree verified in Langfuse v2 observations; Jaeger also verified during integration. |
| Live Copilot agents | First cohort: 2/27 accepted-correct; 25 child failures, mostly turn/tool-budget exhaustion. Release gate failed; protocol correction and requalification are required. |
| Intake live cohort | 24/27 accepted-correct: all S1 leak/localization and S5 missing-data answers passed. Three first-repetition S2 answers failed abstention propagation. Live baseline passed. |
| Final live qualification | 27/27 accepted-correct; all nine distinct scenario/question cases repeated three times. Actual `gpt-6.1-sol`, CLI `1.0.105`, identity source `cli_event`; baseline passed and stored Langfuse tree verified. |
| Browser | All three real-Chrome cases passed: controls, moving windows, keyboard sensor selection, charts/raw evidence, pinned questions/tasks, truthful counters, all pipeline chips and reconnect stability. |
| One-page brief | Original PDF rendered with installed Chrome; exactly one page verified. |
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
