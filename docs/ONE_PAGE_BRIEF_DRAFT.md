# Subsea Integrity Copilot

**Prospect and problem.** NorthSea Integrity Operations is a fictional offshore gas
operator. Its monitoring, integrity and instrumentation engineers must distinguish
possible leaks from sensor/telemetry faults and identify what to verify. Manual
correlation is slow; unnecessary inspection is costly; dismissing a leak is dangerous.

**Why this problem.** My supplied marine data-quality thesis informs missing-data
handling, interpretable anomaly detection and expert involvement. Defense slide 47
motivates distributed observations. Spatial leak diagnosis and localization are new
demo extensions, not thesis-validated capabilities.

**Why unsigned.** The existing dashboard is cheaper; false alarms, localization,
integration effort and data sovereignty remain objections.

**The two customer roles.** The **Head of Subsea Operations** owns the budget and
cares about cost, delivery time, inspection disruption and liability. Their objection:
"Why pay for another alarm system, and what happens when it is wrong?" The **Lead
Subsea Integrity & Instrumentation Engineer** cares about sensor independence,
physical assumptions, data quality and reproducibility. Their objection:
"Simultaneous alarms could be a shared failure. How do you infer the pipeline section?"

**Proposed demo.** An original synthetic network with 24 sensor nodes combines
acoustic relative power, dissolved methane and temperature context in a continuous
60-second window advancing every 5 simulated seconds. Real defects
include gaps, spikes, mixed units/time formats and conflicting duplicates. A bounded
three-agent workflow answers: (1) possible leak or instrumentation issue?
(2) which section should an engineer inspect first, and why?
(3) which sensors are unreliable and what evidence is missing?
Deterministic tools own normalization, topology correlation and numerical localization;
separately scoped quality, diagnosis and response agents interpret checked, cited
findings through the GitHub Copilot CLI proxy. A simultaneous gateway outage
demonstrates why missingness is not physical leak evidence.
An original interactive console exposes replay controls, sensor evidence and agent
traces. CustomerOps' Python/PostgreSQL/TypeScript stack uses LangChain interfaces,
LangGraph workflows and self-hosted Langfuse observability.

**Acceptance and risk.** Separate sensor health from event hypotheses; require usable,
persistent, independently corroborated evidence. Show alternatives and withhold
unsupported location. Retain provenance, test hidden-label cases and report failures.
Humans retain inspection, control and safety authority.

**Commercial next step.** Propose a conditional four-week read-only shadow pilot on
one network after data/security approval, with operator-reviewed accuracy, false alarms,
latency and triage effort. Illustrative capacity value: 120 alerts/month x 15 minutes
saved x USD 100/hour = USD 36,000/year; not verified savings. Pilot pricing and scope
require commercial approval. Real labeled events or validated test evidence are needed
to assess leak sensitivity.

**Assumptions and limitations.** Fictional customer and synthetic-only data; assumed
geometry, independence and gas-leak signatures. Simplified acoustic distance-decay
fit gives a compatible pipeline range, not precise triangulation or a calibrated
confidence interval. No shutdown, live historian connector, certified detection/
production isolation or DanaOS integration. The design follows CustomerOps
governance patterns and AITOMATIC's public positioning; it does not claim platform
equivalence. Copilot CLI is local, but proxy inference is not local-only; only synthetic
evidence is used.

**Submission package.** Implemented demo; qualification results and limitations are
in the repository. Private GitHub:
https://github.com/ntnguyen-so/subsea-integrity-copilot.
Grant reviewer access and email this brief/link at least 24 hours before the meeting.
