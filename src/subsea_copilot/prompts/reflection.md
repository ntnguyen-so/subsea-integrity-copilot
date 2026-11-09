---
prompt_id: subsea.reflection
version: 1.4.0
---
Return only InterpretationRevision JSON: {"revisions":[{"paragraph_id":"...",
"text":"...","references":["..."]}]}. Return exactly one replacement for each
revision_targets entry and nothing else. Do not return a full interpretation.
The application preserves all supported explanations and checked fields
unchanged. Use original source_texts, not the
critic as factual authority. The sources are exactly those available to the
reviewer, including the complete read-evidence bundle. Do not call retained
measurements unavailable; decode each evidence group's shared fields and value
columns. Check the named sensor, period and baseline before copying a number.

Revise only the supplied rejected explanations. Preserve their existing
full-ID suspected-instrument inventory, missing-only inventory and numerical
reasons unless the cited measurements contradict a finding. Keep missing
readings separate from diagnosed faults. Include paired/spatial comparisons
and explain their meaning for each material finding. Do not promote pressure
patterns or records into a physically confirmed cause.

Resolve every correction in the reviewer feedback against the complete cited
source, not just the first named example. Keep gap inventories within their
explicit pinned-window scope. Historical gap examples may be explicitly
non-exhaustive; do not create a new exhaustive multi-period inventory during
repair. Preserve all supported instrument diagnoses and material coverage limits,
and verify every count or period you retain.
Work through EVERY critic_feedback.corrections entry for each rejected unit.
Locate its exact excerpt, verify the instruction using its source_references
against source_texts, and apply the required factual or uncertainty correction.
The checklist is not factual authority: if it conflicts with a source, remove
or qualify the unsupported claim using that source rather than copying the
reviewer. Preserve supported units unchanged and do not add unrelated claims.

For current normal-relative pressure, use recent_5s_pressure_drop_bar over the
source's final five seconds; positive means below the supplied reference.
Historical profile deltas use their own pre-split reference, not the normal
baseline. Never substitute a long-window conditional median for a current value.
State a gap only if the particular measurement is genuinely absent.

Use the exact source_texts keys in references. Cite the read-evidence bundle
for its measurements, and separately cite comparisons, records and applicable
KN guidance. Regional sensor_ids must appear in the comparisons cited by that
region. Keep internal source IDs out of prose.

When the answer is a revision target, it is authoritative for map findings;
keep all material diagnoses
and their numerical reasons there. Target at most 5500 characters to leave
headroom below the 6000-character hard limit. Keep causes and regional
explanations to 1-3 sentences with a representative measured comparison, not
copies of the main report. Preserve supported inspection focus, explicit
uncertainty and physical-verification boundaries. Do not invent measurements,
procedures, authority or confidence scores.
For a rejected question return its revised question text and an empty references
array. Do not change cause identifiers, stances, regional sensor IDs or hypotheses.
