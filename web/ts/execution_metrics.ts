import { box, node, text } from "./dom";
import type { AgentTask, ExecutionUsage } from "./types";

const active = new Set(["QUEUED", "RUNNING", "WAITING_ON_CHILD"]);
export class ExecutionMetrics {
  private root: AgentTask | null = null;
  private recorded = false;
  private offset = 0;
  private serverTime = "";

  set(root: AgentTask | null, usage: ExecutionUsage | null, recorded: boolean, serverTime: string): void {
    this.root = root; this.recorded = recorded;
    if (serverTime !== this.serverTime) {
      this.serverTime = serverTime;
      this.offset = Date.parse(serverTime) - Date.now();
    }
    const container = box("execution-summary");
    container.hidden = root === null;
    if (!root) return;
    this.tick();
    text("execution-tokens", usage?.reported_calls
      ? `${usage.total_tokens.toLocaleString()} tokens`
      : "Tokens not yet reported");
    text("execution-token-detail", usage?.reported_calls
      ? `${usage.input_tokens.toLocaleString()} input · ${usage.output_tokens.toLocaleString()} output · ${usage.reported_calls}/${usage.reserved_calls} calls reported`
      : "Provider totals arrive after each model call; unavailable counts are not zero.");
    const cost = usage?.cost_usd ?? null;
    text("execution-cost", cost !== null
      ? `$${cost.toFixed(4)}`
      : "Cost not yet available");
    text("execution-cost-reason", "Standard input and output rates; all input billed at the input rate.");
    text("execution-cost-detail", usage
      ? `Based on ${usage.priced_calls} of ${usage.reserved_calls} model calls${usage.priced_calls < usage.reserved_calls ? "; unpriced calls are excluded" : ""}. Not a Copilot charge.`
      : "No reported usage available for API-equivalent pricing.");
    const pricing = box("execution-pricing");
    pricing.replaceChildren();
    if (usage) {
      pricing.append(node("p", `What this means: an estimate of what the reported usage would cost at OpenAI Standard API rates, not what Copilot bills you. Rates checked ${usage.pricing_date}.`));
      pricing.append(node("p", "Estimate = input tokens × input rate + output tokens × output rate. Reasoning tokens are already included in output. Each model call with more than 272,000 input tokens uses the higher long-context rates."));
      pricing.append(node("p", "Excludes calls with missing usage or unknown rates, regional/FedRAMP surcharges, tools, infrastructure and taxes."));
      for (const [model, rates] of Object.entries(usage.rates_per_million)) {
        const table = node("table");
        table.append(node("caption", `${model} - USD per 1 million tokens`));
        const header = node("tr");
        for (const label of ["Token type", "Up to 272,000 input tokens per call", "Over 272,000 input tokens per call"]) {
          const cell = node("th", label); cell.scope = "col"; header.append(cell);
        }
        const head = node("thead"); head.append(header); table.append(head);
        const body = node("tbody");
        for (const [index, label] of ["Input", "Output (includes reasoning)"].entries()) {
          const row = node("tr"), heading = node("th", label); heading.scope = "row";
          row.append(heading, node("td", `$${rates.short[index]}`), node("td", `$${rates.long[index]}`));
          body.append(row);
        }
        table.append(body); pricing.append(table);
      }
      const source = node("a", "OpenAI pricing source");
      source.href = "https://developers.openai.com/api/docs/pricing";
      source.target = "_blank"; source.rel = "noopener noreferrer"; pricing.append(source);
    }
  }

  tick(): void {
    if (!this.root) return;
    const running = !this.recorded && active.has(this.root.state);
    const end = running ? Date.now() + this.offset : Date.parse(this.root.updated_at);
    const seconds = Math.max(0, Math.floor((end - Date.parse(this.root.created_at)) / 1000));
    const elapsed = `${Math.floor(seconds / 60).toString().padStart(2, "0")}:${(seconds % 60).toString().padStart(2, "0")}`;
    const state = this.recorded ? "Recorded duration" : this.root.state === "QUEUED" ? "Queued"
      : running ? "Running" : this.root.state === "SUCCEEDED" ? "Completed" : this.root.state;
    text("execution-elapsed", `${state} · ${elapsed}`);
    box("execution-summary").classList.toggle("execution-running", running && this.root.state !== "QUEUED");
  }
}
