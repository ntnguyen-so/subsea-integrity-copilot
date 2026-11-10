# Subsea Integrity Copilot - Customer Brief

Subsea pipelines carry oil and gas from offshore fields. Operators monitor pressure along these pipelines to spot possible problems and decide when to intervene. A missed leak can harm the marine environment, stop production and put operating permissions at risk. But sending a vessel or underwater inspection team to investigate faulty measurements can also be costly. The integrity engineer must therefore distinguish a real pipeline problem from a measurement problem before directing a response.

Making that distinction is difficult because different causes can produce similar alerts. A pressure drop may indicate a leak, an operating change or a faulty sensor; missing readings can obscure the picture. A leak and sensor faults may also occur together. Before directing a response, the engineer must establish what is happening, where attention is needed and whether the evidence is reliable enough to act on. This turns each investigation into three practical questions:

1. Is this a leak, a change in operating or measurement conditions, or an instrument problem?

2. If a leak is suspected, which branch and section should be inspected?

3. What evidence supports that conclusion, and what still needs checking before a team is sent?

The illustration below shows this challenge on a simulated 11.2 km network with seven connected sections (P1-P7) and 112 pressure instruments. A leak on P5 occurs alongside sensor faults, missing data and a shared data-connection problem on P7. Both maps summarize the same 60-second slice of simulated readings, from 50 to 110 seconds into the replay, with 69 instruments flagged.

![Dashboard crop: individual pressure alerts and missing readings across seven pipeline segments](assets/brief-sensor-alerts.png)

Figure 1. Sensor alerts only. Orange dots show unusual pressure; dashed dots show missing or invalid readings. To answer question 1, the engineer must compare readings over time and check records to distinguish the P5 leak from P7's connection problem and sensor faults. Question 2 requires tracing related pressure changes across connected branches to narrow the inspection area. Question 3 requires checking sensor reliability and documenting which readings and records support the conclusion. The map alone answers none of these: repeated cross-checks take time and require knowledge of pipeline behavior.

Subsea Integrity Copilot helps answer these same questions as monitoring continues. Its AI agents compare related measurements and records, assess possible causes, suggest an inspection priority and link findings to their evidence. This gives the engineer an investigation to review rather than assemble from individual alerts.

![Dashboard crop: suspected P5 leak, report-stated inspection priority and separate instrument issues](assets/brief-agent-assisted.png)

Figure 2. Agent-assisted investigation. For question 1, the report distinguishes a suspected P5 leak (red) from separate sensor or data concerns (purple rings, not confirmed hardware failures). For question 2, it prioritizes inspection at 700-900 m from P5's start (green). For question 3, the accompanying report provides supporting readings and records, along with uncertainties and further checks. The engineer reviews these findings before deciding how to respond. The system assists that judgment; it does not confirm an exact leak location or authorize deployment.

This handoff also needs to be timely so the engineer can assess a developing problem. In two separate controlled tests of this simulated scenario, reviewed reports were ready in about 2.5-2.8 minutes of elapsed time, excluding map updates. These observations measure report preparation, not field response, and do not establish a production response-time guarantee.

[Run the demo](https://github.com/ntnguyen-so/subsea-integrity-copilot). [Dashboard evidence](https://github.com/ntnguyen-so/subsea-integrity-copilot/blob/main/docs/evidence/brief-dashboard-comparison.json). [Timing and limitations](https://github.com/ntnguyen-so/subsea-integrity-copilot/blob/main/docs/RESULTS.md).
