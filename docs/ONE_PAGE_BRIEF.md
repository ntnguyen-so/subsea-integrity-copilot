# Subsea Integrity Copilot - Customer Brief

Subsea pipelines carry oil and gas beneath the sea. A missed leak can damage the marine environment, interrupt production and trigger regulatory action, potentially including loss of operating permissions. Mistaking faulty measurements for a leak can also cause unnecessary vessel or remotely operated vehicle deployments.

Pressure-monitoring alerts do not explain their cause. Missing readings, instrument faults, changes in measurement conditions or operations, and genuine leaks can look similar. Integrity engineers must correlate many sensors across connected branches, check their timing and reliability, and consult operating and maintenance records. This requires domain knowledge and time; leaks and instrument problems can occur together. Engineers must answer three questions:

1. Is the anomaly a leak, a disturbance affecting the measurements, or an instrument problem?

2. If a leak is suspected, which pipeline branch and section should be inspected?

3. Which readings and records support the leak or instrument-fault conclusion, and what must be verified before deploying maintenance teams?

The S7 scenario makes this concrete: a simulated 11.2 km network with seven connected pipe sections (P1-P7) and 112 pressure instruments. A P5 leak overlaps with spikes, drift, missing or frozen readings, and a shared connection problem on P7. The following dashboard crops use identical readings and alerts.

![Dashboard crop: individual pressure alerts and missing readings across seven pipeline segments](assets/brief-sensor-alerts.png)

Figure 1. Sensor alerts only. In this one-minute window, 69 instruments are flagged. The engineer must open and align pressure histories, compare neighboring and paired sensors, check shared connections, and read operating and maintenance records. Orange dots indicate unusual pressure; dashed dots indicate missing or invalid readings, not where a leak is. Separating P5's leak pattern from P7's connection problem and individual faults requires repeated cross-checking and domain knowledge. This manual correlation, not spotting colored markers, consumes the engineer's time.

![Dashboard crop: suspected P5 leak, report-stated inspection priority and separate instrument issues](assets/brief-agent-assisted.png)

Figure 2. Agent-assisted investigation. Subsea Integrity Copilot's AI agents compare related measurements, check records and assemble cited findings for the engineer. Red identifies P5 as the suspected branch; green focuses inspection planning on 700-900 m from its start. Purple rings retain separate instrument/data concerns. Instead of starting from individual alerts, the engineer reviews an organized explanation, competing causes, supporting evidence and next verification steps. The system supports ongoing investigation; it does not confirm exact leak coordinates or authorize automatic deployment.

Numerical alerts do not wait for AI. Two controlled S7 rehearsals produced reviewed reports in about 2.5-2.8 minutes, excluding map updates. This is not a production response-time guarantee.

[Run the demo](https://github.com/ntnguyen-so/subsea-integrity-copilot). [Dashboard evidence](https://github.com/ntnguyen-so/subsea-integrity-copilot/blob/main/docs/evidence/brief-dashboard-comparison.json). [Timing and limitations](https://github.com/ntnguyen-so/subsea-integrity-copilot/blob/main/docs/RESULTS.md).
