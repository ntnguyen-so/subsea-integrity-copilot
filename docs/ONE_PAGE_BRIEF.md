# Subsea Integrity Copilot - Customer Brief

Subsea pipelines carry oil and gas from offshore fields. Operators monitor pressure along these pipelines to spot possible problems and decide when to intervene. A missed leak can harm the marine environment, stop production and put operating permissions at risk. But sending a vessel or underwater inspection team to investigate faulty measurements can also be costly. The integrity engineer must therefore distinguish a real pipeline problem from a measurement problem before directing a response.

Making that distinction is difficult because different causes can produce similar alerts. A pressure drop may indicate a leak, an operating change or a faulty sensor; missing readings can obscure the picture. Engineers must compare how measurements change over time and along connected branches, check which sensors share a data connection, and consult operating and maintenance records. A leak and sensor faults may occur together, so no single alert settles the diagnosis. The investigation must answer three questions:

1. Is this a leak, a change in operating or measurement conditions, or an instrument problem?

2. If a leak is suspected, which branch and section should be inspected?

3. What evidence supports that conclusion, and what still needs checking before a team is sent?

Subsea Integrity Copilot helps with this investigation as monitoring continues. Its AI agents bring related measurements and records together, assess possible causes and prepare an evidence-linked explanation for the engineer to review. The aim is to support a timely, informed response, not replace engineering judgment.

The S7 demonstration illustrates the challenge on a simulated 11.2 km network with seven connected sections (P1-P7) and 112 pressure instruments. A leak on P5 occurs alongside sensor faults, missing data and a shared data-connection problem on P7. Both views below use the same readings and alerts.

![Dashboard crop: individual pressure alerts and missing readings across seven pipeline segments](assets/brief-sensor-alerts.png)

Figure 1. Sensor alerts only. In this one-minute window, 69 instruments are flagged. Orange dots show unusual pressure; dashed dots show missing or invalid readings. Neither identifies a leak. The engineer must examine readings over time, compare nearby sensors and check records to explain each pattern. Separating the P5 leak from the P7 connection problem and individual sensor faults requires repeated cross-checks and knowledge of pipeline behavior. The workload lies in explaining how the alerts relate, not simply finding them on the map.

![Dashboard crop: suspected P5 leak, report-stated inspection priority and separate instrument issues](assets/brief-agent-assisted.png)

Figure 2. Agent-assisted investigation. The agents assemble the comparisons and records into findings with supporting evidence. Red marks P5 as the suspected leaking branch; green shows the report's inspection priority, 700-900 m from its start. Purple rings mark separate sensor or data concerns, not confirmed hardware failures. The engineer can review the proposed cause, evidence and unresolved questions rather than assemble the investigation from individual alerts. This guides further checks; it does not confirm an exact leak location or authorize deployment.

Numerical alerts do not wait for AI. Two controlled S7 rehearsals produced reviewed reports in about 2.5-2.8 minutes, excluding map updates. This is not a production response-time guarantee.

[Run the demo](https://github.com/ntnguyen-so/subsea-integrity-copilot). [Dashboard evidence](https://github.com/ntnguyen-so/subsea-integrity-copilot/blob/main/docs/evidence/brief-dashboard-comparison.json). [Timing and limitations](https://github.com/ntnguyen-so/subsea-integrity-copilot/blob/main/docs/RESULTS.md).
