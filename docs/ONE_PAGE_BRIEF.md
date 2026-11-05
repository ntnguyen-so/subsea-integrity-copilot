# Subsea Integrity Copilot - Customer Brief

**Customer, problem and users.** NorthSea Integrity Operations is a fictional
offshore gas operator monitoring subsea pipelines with distributed sensors.
Its monitoring, integrity and instrumentation engineers must distinguish a possible
pipeline leak from scattered sensor faults or a shared telemetry outage, then decide
what evidence and pipeline section to inspect. Manual correlation is slow;
unnecessary offshore inspection is expensive, while dismissing a leak is dangerous.

**Why I chose this problem.** It builds on my marine anomaly-detection and
data-quality research: imperfect observations, spatial/temporal patterns and expert
interpretation. It is a useful FDE problem because the customer needs a defensible
operational decision, not another alarm or a fluent chatbot. Leak localization is
a new, simplified demo extension, not a capability validated by my thesis.

**Why the prospect has not signed.** Their existing dashboard is cheaper.
They doubt whether AI will reduce investigation effort without adding false alarms,
integration work or safety liability. They also question localization accuracy
and whether sensitive operational data would leave their environment.

**Business stakeholder: Head of Subsea Operations, budget owner.** Cares about
cost, delivery time, inspection disruption, adoption and risk. Main objections:
"Why pay for another alarm system?", "What measurable value will a pilot deliver?"
and "Who is responsible when the recommendation is wrong?" The proposed commitment
is a bounded, read-only shadow pilot, not a replacement for safety procedures.

**Technical stakeholder: Lead Subsea Integrity & Instrumentation Engineer.**
Cares about sensor calibration and independence, provenance, missing data,
physical assumptions, reproducibility and integration. Main objections:
"Simultaneous anomalies could share a failed gateway", "What supports this
inspection location?" and "Can I inspect the raw records and reproduce the answer?"

**What the demo demonstrates.** An original synthetic network of 24 sensor nodes
streams acoustic relative power, dissolved methane and temperature through a
60-second window advancing every five simulated seconds. Data includes gaps,
spikes, mixed units/time formats and conflicting duplicates. Three scoped agents
answer: (1) possible leak or instrumentation issue? (2) which pipeline section
should an engineer inspect first, and why? (3) which sensors are unreliable and
what evidence is missing? Numerical tools own normalization, corroboration and
fitting; agents interpret checked evidence. The console exposes sensor records,
pinned answers and execution receipts. A shared outage demonstrates abstention.

**Assumptions and limitations.** The customer, network and telemetry are synthetic;
no confidential employer data is used. Geometry, baseline history, failure domains
and gas-leak signatures are assumed. Acoustic distance-decay fitting provides a
compatible inspection candidate, not an exact leak position or calibrated confidence
interval. Synthetic qualification is not field reliability. Missingness does not
prove a leak or a particular hardware failure. Copilot inference is hosted, not
local-only; only synthetic evidence is sent. There is no live historian connector,
certified detection, shutdown/control capability, production security certification
or claimed DanaOS integration. Human engineers retain inspection and safety authority.

**Proposed next step.** A conditional four-week shadow pilot on one network after
data/security approval. Jointly measure triage effort, reviewed false alarms,
coverage and latency; assess sensitivity only with labeled events or validated tests.
Pricing, savings assumptions and acceptance gates must be agreed with the customer.

**Private demo repository:** https://github.com/ntnguyen-so/subsea-integrity-copilot
