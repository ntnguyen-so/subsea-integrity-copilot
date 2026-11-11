import { button, friendly, node, time } from "./dom";
import type { KnowledgePacket } from "./types";

export interface MaintenanceRecord {
  id: string; title: string; type: "maintenance"; asset_ids: string[];
  authored_at: string; available_at: string; effective_from: string; effective_to: string | null;
  revision: number; supersedes: string | null; status: "approved" | "draft" | "superseded";
  body: string; admissible: boolean; exclusion_reason: string | null;
}
export interface MaintenanceCatalog {
  generation_id: string; site_id: string; pack_version: string; source_seconds: number;
  scenario: string; duration_seconds: number; next_effective_seconds: number | null;
  source_file: string; knowledge_source_file: string;
  as_of: string; corpus_version: string; records: MaintenanceRecord[]; knowledge: KnowledgePacket;
}

export class MaintenancePanel {
  private key = "";
  private pending: AbortController | null = null;
  private version = 0;
  private activeTopic = "maintenance";

  constructor(private readonly container: HTMLElement,
    private readonly get: <T>(path: string, signal: AbortSignal) => Promise<T>,
    private readonly selectTime: (seconds: number) => void) {}

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
      `${catalog.scenario} · Source time +${catalog.source_seconds}s · ${time(catalog.as_of)} · ${effectiveRecords.length} effective maintenance record(s).`, "summary");
    basis.dataset.generation = catalog.generation_id;
    basis.dataset.sourceSeconds = String(catalog.source_seconds);
    const records = node("section");
    const heading = node("h3", "Maintenance records"); heading.id = "maintenance-documents-title";
    const sourceFile = node("p", "", "public-record");
    sourceFile.textContent = `Source file (repository-relative): ${catalog.source_file}`;
    const controls = node("div", "", "investigation-time-control");
    const label = node("label", "Maintenance source time"); label.htmlFor = "maintenance-source-time";
    const sliderRow = node("div", "", "investigation-time-slider");
    const slider = node("input"); slider.id = label.htmlFor; slider.type = "range";
    slider.min = "0"; slider.max = String(catalog.duration_seconds); slider.step = "1";
    slider.value = String(catalog.source_seconds);
    const selectedTime = node("output", `+${catalog.source_seconds}s`);
    slider.addEventListener("input", () => { selectedTime.value = `+${slider.value}s`; });
    slider.addEventListener("change", () => this.selectTime(Number(slider.value)));
    sliderRow.append(slider, selectedTime);
    controls.append(label, sliderRow, node("p",
      "Changes the selected source time, not the live run. Browsing records does not start agents.", "muted"));
    records.append(heading, sourceFile, controls, basis, node("p",
      "Reference catalog, not an inventory of documents read by an agent. Only approved records effective at this source time are shown; draft, superseded, expired and future records are withheld.", "muted"));
    if (!effectiveRecords.length) {
      records.append(node("p",
        `No effective maintenance records are available for ${catalog.scenario} at +${catalog.source_seconds}s. This does not establish that no maintenance occurred.`, "empty"));
      const next = catalog.next_effective_seconds;
      if (next !== null) records.append(node("p",
        `The next eligible reference is available at +${next}s. Its contents remain hidden until you select that time.`, "summary"),
      button(`View records at +${next}s`, () => this.selectTime(next)));
    }
    for (const record of effectiveRecords) {
      const card = node("article", "", "history-investigation");
      card.dataset.document = record.id;
      card.dataset.admissible = String(record.admissible);
      const title = node("h3"); title.textContent = record.title;
      const body = node("p"); body.textContent = record.body; body.dataset.maintenanceBody = record.id;
      const sourceRecord = node("p", "", "public-record");
      sourceRecord.textContent = `Source JSON record: records[].id = ${record.id}`;
      card.append(title, sourceRecord, node("p", `Applies to: ${record.asset_ids.join(", ")}`, "muted"), body,
        node("p", "Approved and within its effective period at this source time. Approval alone does not prove that work was executed.", "summary"),
        node("p", `Document effective from ${time(record.effective_from)} to ${record.effective_to ? time(record.effective_to) : "no recorded end"}. Activity timing is described in the record above.`, "muted"));
      const metadata = node("details");
      metadata.append(node("summary", "Record identity and provenance"),
        node("p", `${record.id} · revision ${record.revision} · ${record.status}`),
        node("p", `Authored: ${time(record.authored_at)} · Available: ${time(record.available_at)}`, "muted"));
      if (record.supersedes) metadata.append(node("p", `Replaces revision: ${record.supersedes}`));
      card.append(metadata); records.append(card);
    }
    const provenance = node("details");
    provenance.append(node("summary", "Reference corpus and evidence boundary"),
      node("p", `Corpus version: ${catalog.corpus_version} · Layout: ${catalog.pack_version}`, "public-record"),
      node("p", "Synthetic reference records; not a live maintenance-management feed. The catalog does not prove a sensor fault, a pressure-event cause, completed work or safety clearance.", "muted"));
    records.append(provenance);
    const panels = [records, this.renderKnowledge(catalog.knowledge, catalog.knowledge_source_file)];
    const tabs = node("div", "", "evaluation-suite-selector");
    tabs.setAttribute("role", "tablist"); tabs.setAttribute("aria-label", "Knowledge topics");
    const selectTopic = (index: number, focus = false): void => {
      this.activeTopic = index === 0 ? "maintenance" : "pressure";
      buttons.forEach((tab, position) => {
        const selected = position === index;
        tab.setAttribute("aria-selected", String(selected)); tab.tabIndex = selected ? 0 : -1;
        panels[position].hidden = !selected;
        if (selected && focus) tab.focus();
      });
    };
    const buttons = [["maintenance", "Maintenance"], ["pressure", "Pressure Investigation"]].map(([key, label], index) => {
      const tab = node("button", label); tab.type = "button"; tab.setAttribute("role", "tab");
      tab.id = `knowledge-${key}-tab`; tab.setAttribute("aria-controls", `knowledge-${key}-panel`);
      panels[index].id = `knowledge-${key}-panel`; panels[index].setAttribute("role", "tabpanel");
      panels[index].setAttribute("aria-labelledby", tab.id);
      tab.addEventListener("click", () => selectTopic(index));
      tab.addEventListener("keydown", event => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        selectTopic(event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1
          : (index + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length, true);
      });
      return tab;
    });
    tabs.append(...buttons);
    this.container.replaceChildren(tabs, ...panels);
    selectTopic(this.activeTopic === "maintenance" ? 0 : 1);
  }

  private renderKnowledge(packet: KnowledgePacket, sourcePath: string): HTMLElement {
    const section = node("section", "", "history-investigation");
    const heading = node("h3", "Pressure Investigation Knowledge"); heading.id = "pressure-knowledge-title";
    const sourceFile = node("p", "", "public-record");
    sourceFile.textContent = `Source file (repository-relative): ${sourcePath}`;
    section.append(heading, sourceFile, node("p",
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
    section.append(provenance); return section;
  }
}
