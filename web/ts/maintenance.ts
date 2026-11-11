import { friendly, node, time } from "./dom";
import type { KnowledgePacket } from "./types";

export interface MaintenanceRecord {
  id: string; title: string; type: "maintenance"; asset_ids: string[];
  authored_at: string; available_at: string; effective_from: string; effective_to: string | null;
  revision: number; supersedes: string | null; status: "approved" | "draft" | "superseded";
  body: string; admissible: boolean; exclusion_reason: string | null;
}
export interface MaintenanceCatalog {
  generation_id: string; site_id: string; pack_version: string; source_seconds: number;
  as_of: string; corpus_version: string; records: MaintenanceRecord[]; knowledge: KnowledgePacket;
}

export class MaintenancePanel {
  private key = "";
  private pending: AbortController | null = null;
  private version = 0;

  constructor(private readonly container: HTMLElement,
    private readonly get: <T>(path: string, signal: AbortSignal) => Promise<T>) {}

  clear(message: string): void {
    this.pending?.abort(); this.pending = null; this.version++; this.key = "";
    this.container.replaceChildren(node("p", message, "empty"));
  }

  async load(generation: string, seconds: number): Promise<void> {
    const key = `${generation}:${seconds}`;
    if (key === this.key) return;
    this.clear("Loading maintenance records for this source time. Previous records withheld.");
    this.key = key;
    const version = this.version, controller = new AbortController();
    this.pending = controller;
    try {
      const catalog = await this.get<MaintenanceCatalog>(
        `/api/replays/${encodeURIComponent(generation)}/maintenance?source_seconds=${seconds}`, controller.signal);
      if (version !== this.version) return;
      if (catalog.generation_id !== generation || catalog.source_seconds !== seconds) {
        throw new Error("Maintenance record scope mismatch");
      }
      this.render(catalog);
    } catch (error) {
      if (version !== this.version || controller.signal.aborted) return;
      this.key = "";
      this.container.replaceChildren(node("p", `Maintenance unavailable: ${
        error instanceof Error ? error.message : "Unexpected backend response"
      }. No previous records or maintenance conclusions substituted.`, "summary"));
    } finally {
      if (version === this.version) this.pending = null;
    }
  }

  private render(catalog: MaintenanceCatalog): void {
    const effectiveRecords = catalog.records.filter(record => record.admissible);
    const basis = node("p",
      `Source time +${catalog.source_seconds}s · ${time(catalog.as_of)} · ${effectiveRecords.length} effective maintenance record(s).`, "summary");
    basis.dataset.generation = catalog.generation_id;
    basis.dataset.sourceSeconds = String(catalog.source_seconds);
    const records = node("section");
    records.setAttribute("aria-labelledby", "maintenance-documents-title");
    const heading = node("h3", "Maintenance records"); heading.id = "maintenance-documents-title";
    records.append(heading, basis, node("p",
      "Reference catalog, not an inventory of documents read by an agent. Only approved records effective at this source time are shown; draft, superseded, expired and future records are withheld. Change the source time in Live to inspect another point.", "muted"));
    this.container.replaceChildren(records);
    if (!effectiveRecords.length) records.append(node("p",
      "No effective maintenance records are available in this reference corpus at the selected time. This does not establish that no maintenance occurred.", "empty"));
    for (const record of effectiveRecords) {
      const card = node("article", "", "history-investigation");
      card.dataset.document = record.id;
      card.dataset.admissible = String(record.admissible);
      const title = node("h3"); title.textContent = record.title;
      card.append(title, node("p", `${record.id} · revision ${record.revision} · ${record.status}`),
        node("p", "Approved and within its effective period at this source time. Approval alone does not prove that work was executed.", "summary"),
        node("p", `Assets: ${record.asset_ids.join(", ")}`),
        node("p", `Authored: ${time(record.authored_at)} · Available: ${time(record.available_at)}`, "muted"),
        node("p", `Effective: ${time(record.effective_from)} to ${record.effective_to ? time(record.effective_to) : "no recorded end"}`, "muted"));
      if (record.supersedes) card.append(node("p", `Replaces revision: ${record.supersedes}`));
      const body = node("details");
      body.open = true;
      body.append(node("summary", "Original maintenance record"), node("pre", record.body));
      card.append(body); records.append(card);
    }
    const provenance = node("details");
    provenance.append(node("summary", "Reference corpus and evidence boundary"),
      node("p", `Corpus version: ${catalog.corpus_version} · Layout: ${catalog.pack_version}`, "public-record"),
      node("p", "Synthetic reference records; not a live maintenance-management feed. The catalog does not prove a sensor fault, a pressure-event cause, completed work or safety clearance.", "muted"));
    records.append(provenance);
    this.renderKnowledge(catalog.knowledge);
  }

  private renderKnowledge(packet: KnowledgePacket): void {
    const section = node("section", "", "history-investigation");
    section.setAttribute("aria-labelledby", "pressure-knowledge-title");
    const heading = node("h3", "Pressure Investigation Knowledge"); heading.id = "pressure-knowledge-title";
    section.append(heading, node("p",
      "Applicable domain guidance from the same versioned knowledge corpus used by the agents. It suggests checks; it is not incident evidence, a diagnosis or a field-approved operating procedure.", "summary"),
    node("p", `Knowledge selected at ${time(packet.selected_at)} (wall clock), not the simulated maintenance-source clock. This is the current applicable reference, not a saved investigation's historical knowledge packet.`, "muted"));
    if (!packet.cards.length) section.append(node("p",
      "No applicable curated pressure-investigation knowledge is available for this layout. No generic guidance is substituted.", "empty"));
    for (const card of [...packet.cards].sort((a, b) => Number(b.kind === "procedure") - Number(a.kind === "procedure"))) {
      const article = node("article", "", "knowledge-card"); article.dataset.knowledge = card.id;
      const title = node("h4"); title.textContent = card.title;
      article.append(title, node("p", `${card.id} · ${card.kind} · ${friendly(card.status)}`));
      if (card.applies_when) {
        const applies = node("p"); applies.textContent = `When to use: ${card.applies_when}`;
        article.append(applies);
      }
      const details = node("details"); details.open = card.kind === "procedure";
      details.append(node("summary", "Guidance, verification steps and limits"));
      const guidance = node("p"); guidance.textContent = card.guidance; details.append(guidance);
      for (const [label, items] of [
        ["What to verify", card.verification_steps],
        ["Counterexamples and competing explanations", card.counterexamples],
        ["Limits", card.limitations],
      ] as const) {
        if (!items?.length) continue;
        const list = node(label === "What to verify" ? "ol" : "ul");
        for (const item of items) list.append(node("li", item));
        details.append(node("h4", label), list);
      }
      const sources = node("ul");
      for (const source of card.sources) sources.append(node("li",
        `${source.reference} | ${source.locator} | Evidence boundary: ${source.boundary}`));
      details.append(node("h4", "Sources and applicability boundaries"), sources,
        node("p", card.review_basis, "muted"));
      article.append(details); section.append(article);
    }
    const provenance = node("details");
    provenance.append(node("summary", "Knowledge version and authority"),
      node("p", `${packet.version} · authority: ${friendly(packet.authority)}`, "public-record"));
    section.append(provenance); this.container.append(section);
  }
}
