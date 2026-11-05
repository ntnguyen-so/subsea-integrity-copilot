# CLI-only single-agent qualification baseline

This is one independently persisted read-only model task, not the production
three-agent workflow. No child tasks or cached specialist results are authorized.
You have at most three model turns, five tool requests and one repair within those
bounds. Every tool must bind the exact site, snapshot and versions in BOUND_CONTEXT.

Application-owned intake has already read quality.coverage (including pinned
sensor/failure-domain metadata), quality.sensor_patterns, event.assess and eligible
location.fit. Their actual gateway receipts are in application_intake. Interpret
this evidence and submit FINAL now, reserving a turn for a schema repair.
Do not exhaust health pagination or repeat completed reads. Include
partial_health_review when reported. RUNTIME_REPLY_CONSTRAINTS.final_only forbids tools.
Tools own all numerical calculations and validity exclusions. Preserve usable
anomalies as observations; sensor faults and physical event support can coexist.
Pages disclose additional unreviewed findings. No SQL, shell, files, URLs or controls.

Return only inner AgentResult JSON with outcome, claim_refs, evidence_ids,
limitations, hypothesis, recommendation_ids and summary (""). Use only claims
actually returned by these tools. Cite all referenced source IDs and all material
ledger limitation codes. Select an eligible hypothesis through its exact ledger
claim, or explicitly abstain. A numerical compatible set is not a confidence
interval, and no-event evidence is not a safety decision.

Read-only recommendation IDs: review_sensor_evidence, review_coverage,
review_competing_hypotheses, review_location_fit (eligible fit only).
No free prose, reconstructed arithmetic, confirmed leak, safe operation or shutdown.
Outer transport final value is the inner JSON encoded as a string.
Scripted output is offline contract evidence, never live-model qualification.
