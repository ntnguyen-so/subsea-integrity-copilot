# Subsea Integrity Copilot - Customer Brief

**Prospect and problem.** NorthSea Integrity Operations is a fictional offshore
gas operator. Engineers must distinguish pipeline leaks from sensor spikes,
gaps and drift. Missed leaks threaten the environment and operations; false
alarms trigger costly inspections. Scarce expertise is difficult to encode and
transfer to newcomers.

![Original Y topology and synthetic pressure evidence: related drops support investigation; scattered spikes, gaps and drift suggest sensor faults.](assets/pressure-leak-vs-sensor-faults.svg)

**Why this problem.** My PhD studied marine data quality, anomaly detection and
translating expertise into reviewable smart systems.

**The two customer roles.** The **Head of Subsea Operations** owns the budget:
cost, workload, timeline and risk. The **Lead Subsea Integrity & Instrumentation
Engineer** challenges calibration, shared failures, missing data and unsupported
conclusions. Engineers and newcomers use the copilot.

**Why unsigned.** Doubts about effort savings, hallucinations, missed leaks,
integration cost, privacy and accountability. Cheaper fixed workflows are credible alternatives.

**Monitoring workloads.** Original Y: three 800m pipes, 24 instruments. Extended:
seven branches, 11.2km, 112 instruments; overlapping near/far responses and faults.
Median/MAD feeds sliding-window screening; agents compare joint patterns, records
and failure dependencies. Ambiguous locations are withheld.
Questions: "Leak or faulty sensors?", "Where should we inspect,
and why?" and "What evidence supports this, and what remains unknown?"

**Agent value.** Three scoped roles investigate quality, choose incident-time
history searches/comparisons and explain competing causes. A separate same-model
critic reviews original sources; code checks quotes, coverage and identity.
Revise once, then accept or withhold. Engineers inspect sources and download
evidence. Versioned research-curated guidance is not SME-approved or automatically
acquired expertise.

**Limits and buying gate.** Fictional dirty/conflicting data; unvalidated hydraulics;
intervals, not exact positions. Original cohort: hosted 15/18 first attempts,
then 3/3 explicit retries; fixed 18/18 and faster. No field-accuracy guarantee.
Warnings never wait for inference. Manual time is unmeasured; reports target five
minutes, counting failures and human review separately. Propose a four-week
read-only shadow pilot with agreed quality, abstention, latency and cost gates.
Pricing requires discovery; savings are unproven, connectors unbuilt and hosted
data requires approval. Humans retain safety authority. Buy only if quality,
effort and total cost beat manual/fixed baselines.

**Private GitHub and run instructions:** [github.com/ntnguyen-so/subsea-integrity-copilot](https://github.com/ntnguyen-so/subsea-integrity-copilot). Repository access must be granted before review.
