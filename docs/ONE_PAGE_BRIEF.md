# Subsea Integrity Copilot - Review Brief

**Customer and problem.** NorthSea Integrity Operations is a fictional offshore
gas operator that needs to monitor a long subsea pipeline network. A leak could
release gas into the environment and interrupt operations, so warning signs must
be investigated promptly. To support this, many sensors distributed along the
pipelines continuously stream pressure readings, and existing ML algorithms flag
unusual changes.

The difficulty is that the monitoring equipment can also malfunction. A faulty
sensor may produce sudden spikes, stop reporting measurements or gradually drift
away from its expected readings even when the pipeline is healthy. Engineers
therefore need to assess the quality of the measurements while investigating a
possible leak. Rather than judging each alert in isolation, they must compare
the timing and location of anomalies across several sensors and relate those
patterns to the pipeline layout.

The diagram illustrates this reasoning. On the left, several nearby sensors show
related pressure drops within the same monitoring window. This spatial and
temporal agreement supports a possible leak investigation and helps narrow the
section that may need inspection. By contrast, the scattered spikes, missing
readings and drift on the right suggest individual sensor faults rather than one
localized pipeline event. Neither pattern is conclusive: operating changes can
affect several sensors, and shared communication or equipment failures can also
produce related anomalies.

Today, this investigation depends on a few experienced engineers who combine
sensor histories, pipeline layout and operational knowledge. Their expertise is
difficult to obtain, translate into software and pass to newcomers. At scale,
manual analysis takes time and important warnings may be overlooked among
sensor-related alerts. The proposed solution makes documented expert knowledge
reusable in agent-assisted investigation: distinguish sensor faults from possible
leaks, narrow down where to inspect and explain the evidence to less-experienced
engineers. Initial numerical warnings do not wait for an AI report. It builds on
existing detectors; humans retain safety authority.

![Pressure-monitoring illustration generated from the demo's topology and observations: nearby related anomalies support a leak investigation, while scattered spikes, gaps or drift suggest sensor faults; existing detectors feed agent-assisted investigation and human review.](assets/pressure-leak-vs-sensor-faults.svg)

**Why I chose this problem.** The operator faces two costly mistakes. A missed
leak can cause environmental harm and regulatory breaches that threaten its
licence to operate, including possible revocation for serious or repeated
violations. Conversely, mistaking a sensor fault for a leak can trigger an
unnecessary offshore inspection involving personnel, vessels or an ROV. My PhD
studied marine data quality, anomaly detection and the difficulty of translating
expert knowledge into smart systems. I now want to apply that research in
practice: make expert investigation knowledge reusable while delivering timely,
evidence-backed warnings and inspection guidance.

---

**Proposed workflow.** Keep existing detectors. Agents observe the numerical
evidence, choose read-only searches of incident and maintenance records, and
select pressure-history comparisons to test competing explanations. They check
document status and availability at the incident time, then present cited
evidence, supported inspection areas, contradictions and uncertainty for human
review. The LLM interprets the engineer's question and explains competing
root-cause hypotheses in context: what supports them, what conflicts with them,
and what the engineer should verify next. The review handoff combines this
explanation with the checked inspection interval or explicit withholding,
readable sources, measured comparisons and unresolved questions. Engineers can
draft a follow-up against the same monitoring window and download a versioned
evidence packet. Its citation-linked explanation is separate from checked
measurements; the packet is not a confirmed RCA or engineer approval.
A separate same-model critic reviews every explanation and verification question
against original sources. One revision is allowed; rejected reports are withheld.
Exact quotes and review coverage are code-checked, not a guarantee of correctness.
A logged valve change may make an operating explanation plausible;
it does not rule out a concurrent leak.

**Why agents, not only ML?** Numerical or graph-based methods can correlate
measurements. The agent's additional role is interpreting engineer questions, deciding which
historical evidence to investigate and explaining what it changes. A well-designed fixed workflow
can also solve these small cases; additional model calls must earn their place
against that cheaper baseline.
A separate authored 16-case inspection-priority evaluation matched 15/16
priority sets with hosted interpretation versus 12/16 with context-aware rules.
This tests interpreting operating records to prioritize numerically bracketed
areas, not better leak coordinates or field accuracy. Deprioritized areas are
not cleared of leaks.

**Knowledge transfer.** Versioned research-curated guidance and an investigation
program are pinned with their provenance; incident records are synthetic.
Agents apply the guidance to joint sensor comparisons and competing regional
hypotheses, separately from numerical screening. This is not SME-approved or
automatically acquired tacit expertise. In a customer pilot, experts
must elicit, review and approve procedures and examples before reuse. Compare
newcomer and experienced-engineer decisions; onboarding benefit is a hypothesis,
not a measured result.

**Customer questions.** "Leak or faulty sensors?" "Where should we inspect, and
why?" "What evidence supports this, and what remains unknown?"

**Why unsigned.** They doubt AI will reduce investigation effort. False alarms
mean costly offshore inspections; missed leaks risk damage, disruption and regulatory
action, including possible licence revocation for serious violations. Privacy,
integration cost and accountability remain concerns.

**Budget owner: Head of Subsea Operations.** Cares about workload, inspection cost
and safety. "What will this save, cost and take to deploy?"

**Technical expert: Lead Subsea Integrity & Instrumentation Engineer.** Cares
about calibration, missing data and physical assumptions. "Can you distinguish
pressure transients, shared failures and leaks, and reproduce the conclusion?"

**Current implementation and limits.** The prototype streams synthetic pressure
readings through lightweight anomaly detectors and agent-assisted investigation,
including gaps, spikes and drift. It recommends a station-supported inspection
interval, not an exact leak position. A PostgreSQL full-text retrieval corpus
contains fictional operating logs, maintenance reports and procedures, including
superseded, expired and future-dated records. Searches and comparisons are scoped
to the incident and retain executed tool receipts. The pressure profile is
illustrative, not a validated hydraulic model. Customer detector, historian and
maintenance-system integrations remain unimplemented; operating context and
causation require human verification.
No confidential data. Inference is hosted, not local-only. Read-only decision
support, not certified protection or plant control; humans retain safety authority.

**Pilot.** Treat ten minutes per manual investigation as an assumption to validate.
Aim for a usable AI report within five minutes; immediate numerical warnings are
measured separately and never gated by inference. Compare accuracy, false/missed
warnings, interval containment, unsupported claims, abstention and reliability
under outages against manual/fixed baselines. Include failed and late attempts,
not only successful answers. Zero observed unsupported claims is an acceptance
goal, not a guarantee of hallucination-free language. Adopt only if evidence
quality, knowledge transfer and total cost justify deployment.

**Private demo repository:** https://github.com/ntnguyen-so/subsea-integrity-copilot
