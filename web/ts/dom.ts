import { productText } from "./presentation";

export function element<T extends HTMLElement>(id: string, kind: { new(): T }): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`Required console element missing: ${id}`);
  if (!(node instanceof kind)) throw new Error(`Console element has incompatible type: ${id} is ${node.tagName}`);
  return node;
}
export function box(id: string): HTMLElement { return element(id, HTMLElement); }
export function text(id: string, value: string): void { box(id).textContent = productText(value); }
export function node<K extends keyof HTMLElementTagNameMap>(tag: K, content = "", className = ""): HTMLElementTagNameMap[K] {
  const result = document.createElement(tag);
  result.textContent = ["p", "h3", "h4", "strong", "small", "summary"].includes(tag)
    ? productText(content) : content;
  result.className = className;
  return result;
}
export function button(label: string, action: () => void, className = ""): HTMLButtonElement {
  const result = node("button", label, className);
  result.type = "button";
  result.addEventListener("click", action);
  return result;
}
export function svg<K extends keyof SVGElementTagNameMap>(tag: K, attributes: Record<string, string | number>, content = ""): SVGElementTagNameMap[K] {
  const result = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [name, value] of Object.entries(attributes)) result.setAttribute(name, String(value));
  result.textContent = content;
  return result;
}
export function time(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toISOString().replace("T", " ").replace(/(?:\.000)?Z$/, " UTC");
}
export function bounds(start: string, end: string): string {
  return `[${time(start)}, ${time(end)})`;
}
export function friendly(value: string): string { return value.replace(/_/g, " "); }
