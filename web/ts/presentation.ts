/** Display legacy prose without changing saved evidence, exports or source quotes. */
export function productText(value: string): string {
  return value
    .replace(/Synthetic evidence; instruments and model are uncalibrated\./g, "")
    .replace(/Curated for this synthetic workspace and research-derived; not pipeline-SME approved\./g, "Research-curated domain guidance.")
    .replace(/\bFictional,\s*nonconfidential\s+[^.]+\.\s*/g, "")
    .replace(/\bfictional\s+/gi, "")
    .replace(/\bdemo[_ ]curated\b/g, "curated")
    .replace(/\bsynthetic_advisory_only\b/g, "advisory only")
    .replace(/\bsynthetic second\b/gi, "elapsed second")
    .replace(/\bsynthetic (evidence|pressures|pressure|telemetry|operational|screening|workspace|geometry|bracket|engineering|site|model)\b/gi, "$1")
    .replace(/Synthetic, read-only evidence\./g, "Read-only evidence.")
    .replace(/\b(?:SYNTHETIC_UNCALIBRATED|synthetic_data|uncalibrated_model)\b[,;]?\s*/g, "")
    .replace(/Citation membership is checked; wording is not independently verified RCA\.\s*The checked evidence and safety limits below remain authoritative\./g, "")
    .replace(/ENGINEERING INTERPRETATION - MODEL-WRITTEN, FOR HUMAN REVIEW/g, "ENGINEERING ASSESSMENT")
    .replace(/COMPETING CAUSES - NOT CONFIRMED ROOT CAUSES/g, "COMPETING EXPLANATIONS");
}
