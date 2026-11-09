/**
 * Display-only wording and report readability transforms, not evidence validation.
 * Stored artifacts retain their synthetic provenance and full precision even when
 * the UI shortens labels, citations or long decimal values.
 */
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

/**
 * Hide recognized internal citation notation, preserving ordinary bracketed prose.
 * Round long display decimals (small values use significant figures, not zero);
 * callers retain the original report and references for audit/export.
 */
export function reportText(value: string, references: readonly string[] = []): string {
  return productText(value)
    .replace(/[\[(]([^[\]()\n]+)[\])]/g, (notation: string, body: string) => {
      const internal = body.split(/[;,]/).every(part => {
        const id = part.trim();
        return references.includes(id)
          || /^(?:ev-\d+|claim-\d+|(?:KN|OP|MAINT|LOG|PROC)-[\w-]+|subsea_[a-f0-9]+|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})$/i.test(id)
          || /^(?:(?:the|both|reviewed|executed)\s+)*(?:comparisons|comparison calls|executed comparisons)$/i.test(id);
      });
      return internal ? "" : notation;
    })
    .replace(/(?<![\w./:-])-?\d+\.\d{8,}(?![\w./:-])/g, token => {
      const measured = Number(token);
      return Math.abs(measured) < 0.01 ? measured.toPrecision(3) : measured.toFixed(3);
    })
    .replace(/[ \t]+([.,;:])/g, "$1")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}
