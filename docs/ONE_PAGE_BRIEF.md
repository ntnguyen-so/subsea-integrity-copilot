# Subsea Integrity Copilot - Customer Brief

**Why it matters.** Subsea pipelines carry oil and gas beneath the sea. A missed leak can damage the marine environment, interrupt production and trigger regulatory action, potentially including loss of operating permissions. Mistaking faulty measurements for a leak can also cause unnecessary vessel or remotely operated vehicle deployments.

**The problem.** Pressure-monitoring alerts do not explain their cause. Missing readings, instrument faults, changes in measurement conditions or operations, and genuine leaks can look similar. Integrity engineers must correlate many sensors across connected branches, check their timing and reliability, and consult operating and maintenance records. This requires domain knowledge and time; leaks and instrument problems can occur together.

**1. Cause:** Is the anomaly a leak, a disturbance affecting the measurements, or an instrument problem?

**2. Location:** If a leak is suspected, which pipeline branch and section should be inspected?

**3. Evidence:** Which readings and records support the leak or instrument-fault conclusion, and what must be verified before deploying maintenance teams?

**How the system helps.** Subsea Integrity Copilot combines ongoing monitoring with AI-assisted investigation. It correlates sensor readings with relevant records, explains competing causes, recommends inspection priorities and provides evidence and uncertainties for maintenance planning. The aim is faster, better-supported action, not simply more alerts or automatic deployment.

**The S7 example.** This simulated 11.2 km network has seven connected pipe sections (P1-P7) and 112 pressure instruments. In the illustrated minute, 69 are flagged. A P5 leak overlaps with spikes, drift, missing or frozen readings, and a shared connection problem on P7. Nearby and paired sensors must be compared with timing and operating records: several alerts can reflect one shared fault, not independent leak evidence. Both diagrams show identical readings and alerts.

| Sensor alerts only | Agent-assisted investigation |
|---|---|
| ![Dashboard crop: individual pressure alerts and missing readings across seven pipeline segments](assets/brief-sensor-alerts.png) | ![Dashboard crop: suspected P5 leak, report-stated inspection priority and separate instrument issues](assets/brief-agent-assisted.png) |
| **Left: alerts still need explanation.** Lines are pipes; paired dots are instruments. Orange marks unusual pressure; dashed outlines mark missing/invalid readings. Hollow dots have no pressure alert, not a guarantee of health. The blue ring selects one instrument. The engineer must connect these observations; no leak diagnosis or inspection priority is supplied. | **Right: findings added to the same readings.** Red flags P5 as the suspected branch, not the entire branch as leaking. Green marks the report's inspection priority, 700-900 m from P5's start. Purple rings identify reported instrument/data concerns. A leak and faulty readings can coexist. These are reviewed report findings, not confirmed faults, exact leak coordinates or deployment authorization. |

**Timeliness.** Numerical alerts do not wait for AI. Two controlled S7 rehearsals produced reviewed reports in about 2.5-2.8 minutes, excluding map updates. This is not a production response-time guarantee.

**Demo:** [run instructions](https://github.com/ntnguyen-so/subsea-integrity-copilot). [Dashboard evidence](https://github.com/ntnguyen-so/subsea-integrity-copilot/blob/main/docs/evidence/brief-dashboard-comparison.json). [Timing and limitations](https://github.com/ntnguyen-so/subsea-integrity-copilot/blob/main/docs/RESULTS.md).
