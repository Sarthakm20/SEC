import type { TraceEvent } from "@/lib/api";
import { ms } from "@/lib/format";
import { StatusDot } from "./Verdict";

// Observable system steps — never the model's private reasoning.
export function Trace({ events, compact = false }: { events: TraceEvent[]; compact?: boolean }) {
  return (
    <ol className="relative flex flex-col gap-2.5">
      {events.map((e, i) => (
        <li key={i} className="flex items-start gap-2.5">
          <StatusDot status={e.status} />
          <div className="min-w-0 flex-1">
            <div className={`text-sm ${e.status === "skip" ? "text-[var(--muted)]" : ""}`}>{e.label}</div>
            {!compact && <TraceDetail e={e} />}
          </div>
          {e.duration_ms > 0 && <span className="num shrink-0 text-xs text-[var(--muted)]">{ms(e.duration_ms)}</span>}
        </li>
      ))}
    </ol>
  );
}

function TraceDetail({ e }: { e: TraceEvent }) {
  const d = e.detail as Record<string, unknown>;
  const bits: string[] = [];
  if (e.step === "plan") {
    bits.push(`planner: ${d.planner}`);
    if (Array.isArray(d.metrics) && d.metrics.length) bits.push(`metrics: ${(d.metrics as string[]).join(", ")}`);
    if (Array.isArray(d.sections) && d.sections.length) bits.push(`sections: ${(d.sections as string[]).join(", ")}`);
    if (Array.isArray(d.notes)) bits.push(...(d.notes as string[]));
  }
  if (e.step === "retrieve" && d.timings) {
    const t = d.timings as Record<string, number>;
    bits.push(`mode: ${d.mode}${d.rerank ? " + rerank" : ""}`);
    bits.push(Object.entries(t).map(([k, v]) => `${k} ${ms(v)}`).join(", "));
  }
  if (e.step === "verify") {
    const un = (d.unsupported_numbers as string[]) ?? [];
    const inv = (d.invalid_citations as string[]) ?? [];
    if (un.length) bits.push(`unsupported numbers: ${un.join(", ")}`);
    if (inv.length) bits.push(`invalid citations: ${inv.join(", ")}`);
  }
  if (e.step === "synthesize" && d.llm_error) bits.push(`LLM unavailable: ${d.llm_error}`);
  if (!bits.length) return null;
  return <div className="mt-0.5 text-xs text-[var(--muted)]">{bits.join(" · ")}</div>;
}
