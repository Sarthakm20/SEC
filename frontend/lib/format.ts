export const SECTION_NAMES: Record<string, string> = {
  item_1: "Item 1 · Business",
  item_1a: "Item 1A · Risk factors",
  item_7: "Item 7 · MD&A",
  item_7a: "Item 7A · Market risk",
  notes: "Notes to financial statements",
};

// Color follows the company, never its position in a filtered list.
const SERIES_ORDER = ["AAPL", "MSFT", "NVDA"];
export function seriesVar(ticker: string): string {
  const i = SERIES_ORDER.indexOf(ticker);
  return `var(--series-${i >= 0 ? i + 1 : 1})`;
}

export function usd(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const v = typeof value === "string" ? Number(value) : value;
  const abs = Math.abs(v);
  const sign = v < 0 ? "−" : "";
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  return `${sign}$${abs.toLocaleString()}`;
}

export function pct(ratio: string | number | null | undefined, digits = 1): string {
  if (ratio === null || ratio === undefined) return "—";
  const v = Number(ratio) * 100;
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(digits)}%`;
}

export function factValue(value: string, unit: string): string {
  if (unit === "USD") return usd(value);
  if (unit === "USD/shares") return `$${Number(value).toFixed(2)}`;
  return Number(value).toLocaleString();
}

export function millions(value: string): string {
  return `$${Math.round(Number(value) / 1e6).toLocaleString()} million`;
}

export function periodText(start: string | null, end: string): string {
  return start ? `${start} → ${end}` : `as of ${end}`;
}

export function pages(start: number | null, end: number | null): string | null {
  if (!start) return null;
  return end && end !== start ? `pp. ${start}–${end}` : `p. ${start}`;
}

export function ms(v: number): string {
  return v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`;
}
