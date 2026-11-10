# Subsea Integrity Copilot - Customer Brief

**Customer and problem.** NorthSea Integrity Operations is a fictional offshore gas operator. Existing detectors flag unusual readings across its pipeline network. Engineers must connect sensor histories, timing, topology, shared gateways and operating records: leaks, sensor faults and operating changes can overlap. An alert is not a diagnosis. This work depends on experienced engineers and is difficult to hand over. Missed leaks risk environmental releases and disruption; false diagnoses can trigger costly vessel or ROV inspections.

**Same data, different investigation.** Actual dashboard crops below share S7, seed 2026, source +50 to +110 seconds, measurements and detector alerts. This is an evidence window, not a measured event-onset time. The alert-only workflow illustrates the assumed customer process.

| Sensor alerts only | Agent-assisted investigation |
|---|---|
| ![Dashboard crop: individual pressure alerts and missing readings across seven pipeline segments](assets/brief-sensor-alerts.png) | ![Dashboard crop: suspected P5 leak, report-stated inspection priority and separate instrument issues](assets/brief-agent-assisted.png) |
| **112 instruments; 69 flagged.** Orange = pressure alert; dashed outline = missing/invalid. The engineer must compare histories, retrieve records and connect the dots. No combined diagnosis or inspection area. | **An investigation to review.** Red = suspected P5 leak; green = report-stated 700-900 m inspection priority; purple = reported instrument issues. Not a confirmed leak location. |

**Three questions to test.** "Leak or faulty sensors?" "Where should we inspect, and why?" "What supports this, and what remains unknown?" Open measured comparisons, cited records, competing explanations and verification steps. A grounding reviewer checks source support; rejected reports are withheld. Unsupported locations stay withheld. Detector warnings never wait for AI. Detection evaluation uses pre-authored synthetic truth; answer-quality ratings are advisory model opinions.

**Buyers and objections.** The **Head of Subsea Operations** asks whether effort saved justifies integration, inference and review costs. The **Lead Subsea Integrity & Instrumentation Engineer** asks whether conclusions survive dirty data, conflicting records and reproduction from source. A cheaper fixed workflow may suffice; AI can be wrong; data access and accountability require approval.

**Offer and buying gate.** Propose a four-week, read-only shadow evaluation on one pipeline, starting after data/security readiness. Before authorization, sign scope, owners, acceptance thresholds and a total-spend cap covering actual Copilot entitlement/usage, hosting, integration, review and support; all prices/effort remain unknown. Compare blinded manual, strong-fixed and agent workflows on independent event-level cases, including all failures and total human handling time. Proposed gates and readiness checklist: [report](https://github.com/ntnguyen-so/subsea-integrity-copilot/blob/main/docs/REPORT.md#commercial-and-meeting-contract). Too few cases means extend or stop, not pass. No savings or response-time guarantee.

**Why this problem.** My PhD studied marine data quality, anomaly detection and translating expert requirements into reviewable software.

**Limits.** Synthetic data, not hydraulic validation or field reliability. Images show a selected recording, not new inference or labor savings. Fresh runs have a 900s deadline, not a response-time guarantee; [measured cohorts and failures](https://github.com/ntnguyen-so/subsea-integrity-copilot/blob/main/docs/RESULTS.md) retain their original conditions. Inspection priorities are not dispatch authorization. Connectors, expert-approved knowledge and human safety authority remain customer prerequisites.

**Demo and run instructions:** [github.com/ntnguyen-so/subsea-integrity-copilot](https://github.com/ntnguyen-so/subsea-integrity-copilot). [Capture evidence](https://github.com/ntnguyen-so/subsea-integrity-copilot/blob/main/docs/evidence/brief-dashboard-comparison.json).
