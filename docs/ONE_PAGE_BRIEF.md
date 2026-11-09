# Subsea Integrity Copilot - Customer Brief

**The decision.** Keep the pressure alerts; improve the investigation that follows. Help an integrity engineer distinguish possible leaks from unreliable instruments, decide where to inspect first, and explain the evidence and uncertainty.

**Customer and problem.** NorthSea Integrity Operations is a fictional offshore gas operator. Existing detectors flag unusual readings across its pipeline network. Engineers must connect sensor histories, timing, topology, shared gateways and operating records: leaks, sensor faults and operating changes can overlap. An alert is not a diagnosis. This work depends on experienced engineers and is difficult to hand over. Missed leaks risk environmental releases and disruption; false diagnoses can trigger costly vessel or ROV inspections.

**Same data, different investigation.** Actual dashboard crops below share S7, seed 2026, source +50 to +110 seconds, measurements and detector alerts. The alert-only workflow illustrates the assumed customer process.

| Sensor alerts only | Agent-assisted investigation |
|---|---|
| ![Dashboard crop: individual pressure alerts and missing readings across seven pipeline segments](assets/brief-sensor-alerts.png) | ![Dashboard crop: suspected P5 leak, report-stated inspection priority and separate instrument issues](assets/brief-agent-assisted.png) |
| **112 instruments; 69 flagged.** Orange = pressure alert; dashed outline = missing/invalid. The engineer must compare histories, retrieve records and connect the dots. No combined diagnosis or inspection area. | **An investigation to review.** Red = suspected P5 leak; green = report-stated 700-900 m inspection priority; purple = reported instrument issues. Not a confirmed leak location. |

**Three questions to test.** "Leak or faulty sensors?" "Where should we inspect, and why?" "What supports this, and what remains unknown?" Open measured comparisons, cited records, competing explanations and verification steps. A grounding reviewer checks source support; rejected reports are withheld. Unsupported locations stay withheld. Detector warnings never wait for AI. Detection evaluation uses pre-authored synthetic truth; answer-quality ratings are advisory model opinions.

**Buyers and objections.** The **Head of Subsea Operations** asks whether effort saved justifies integration, inference and review costs. The **Lead Subsea Integrity & Instrumentation Engineer** asks whether conclusions survive dirty data, conflicting records and reproduction from source. A cheaper fixed workflow may suffice; AI can be wrong; data access and accountability require approval.

**Offer and buying gate.** A proposed four-week, read-only shadow pilot on one pipeline. Agree manual/fixed-workflow baselines, access controls, spend limits and acceptance thresholds first. Measure engineer review time, missed/false findings, unsupported claims, useful inspection priorities and end-to-end failures/latency. Expand only if evidence quality, effort and total cost justify adoption. No savings or response-time guarantee.

**Why this problem.** My PhD studied marine data quality, anomaly detection and translating expert requirements into reviewable software.

**Limits.** Synthetic data, not a validated hydraulic model or field-reliability result. Images show a selected recorded investigation, not a new inference or measured labor saving. Inspection priorities are not dispatch authorization. Production connectors and expert-approved procedures require customer work. Humans retain safety authority.

**Demo and run instructions:** [github.com/ntnguyen-so/subsea-integrity-copilot](https://github.com/ntnguyen-so/subsea-integrity-copilot). [Capture evidence](https://github.com/ntnguyen-so/subsea-integrity-copilot/blob/main/docs/evidence/brief-dashboard-comparison.json).
