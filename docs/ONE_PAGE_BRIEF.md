# Subsea Integrity Copilot - Customer Brief

**The problem.** A pipeline can raise many anomaly alerts without revealing what caused them. Missing data, instrument faults, changes in measurement conditions or operations, and genuine leaks can look similar. Integrity engineers must correlate readings across many sensors and branches, check their timing and reliability, and consult operating and maintenance records. This is time-consuming work requiring domain knowledge: a leak and instrument problems can occur together.

**1. Cause:** Is the anomaly a leak, a disturbance affecting the measurements, or an instrument problem?

**2. Location:** If a leak is suspected, which pipeline branch and section should be inspected?

**3. Evidence:** Which readings and records support the leak or instrument-fault conclusion, and what must be verified before deploying maintenance teams?

**Why S7 is difficult.** This simulated network has seven connected sections and 112 instruments over 11.2 km. In the illustrated minute, 69 instruments are flagged. A simulated P5 leak overlaps with spikes, gradual reading drift, missing or frozen values, and a shared connection problem affecting several P7 sensors. Engineers must compare nearby and paired sensors, timing and operating context to distinguish a leak pattern from a shared fault. Counting alerts is not enough.

| Sensor alerts only | Agent-assisted investigation |
|---|---|
| ![Dashboard crop: individual pressure alerts and missing readings across seven pipeline segments](assets/brief-sensor-alerts.png) | ![Dashboard crop: suspected P5 leak, report-stated inspection priority and separate instrument issues](assets/brief-agent-assisted.png) |
| **The engineer connects the dots.** Orange = pressure alert; dashed outline = missing/invalid. No combined diagnosis or inspection priority. | **A focused investigation to review.** Red = suspected P5 leak; green = reported 700-900 m inspection priority; purple = reported instrument issues. |

**How the system helps.** It monitors incoming measurements on an ongoing basis and assists the engineer by correlating sensor readings with relevant records. It explains competing causes, recommends inspection priorities and provides evidence and uncertainties for maintenance planning. The aim is faster, better-supported action, not simply more alerts or automatic deployment.

**Timeliness.** Numerical alerts do not wait for AI. Two controlled S7 rehearsals produced reviewed reports in about 2.5-2.8 minutes, excluding map updates. This is not a production response-time guarantee.

**Why it matters.** A missed leak can damage the marine environment, interrupt production and trigger regulatory action, potentially including loss of operating permissions. False diagnoses can cause unnecessary vessel or remotely operated vehicle deployments.

**Next step.** A read-only pilot with the Head of Subsea Operations and Lead Integrity Engineer should compare evidence quality, total engineer handling time, response time and cost against manual and fixed workflows.

**Scope.** Illustrative synthetic data, not field validation or proven labor savings. Both dashboard crops use identical measurements and alerts. Inspection priorities are not confirmed leak coordinates or deployment authorization; humans retain safety authority.

**Demo:** [run instructions](https://github.com/ntnguyen-so/subsea-integrity-copilot). [Dashboard evidence](https://github.com/ntnguyen-so/subsea-integrity-copilot/blob/main/docs/evidence/brief-dashboard-comparison.json). [Timing and limitations](https://github.com/ntnguyen-so/subsea-integrity-copilot/blob/main/docs/RESULTS.md).
