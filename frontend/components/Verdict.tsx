import type { Verdict as V } from "@/lib/api";

const META: Record<V, { label: string; color: string; bg: string; icon: string }> = {
  verified: { label: "Verified", color: "var(--ok)", bg: "var(--ok-soft)", icon: "M5 12l5 5 9-10" },
  partially_verified: { label: "Partially verified", color: "var(--warn)", bg: "var(--warn-soft)", icon: "M12 7v6M12 17h.01" },
  insufficient_evidence: { label: "Not enough evidence", color: "var(--none)", bg: "var(--none-soft)", icon: "M8 12h8" },
  failed: { label: "Failed verification", color: "var(--fail)", bg: "var(--fail-soft)", icon: "M7 7l10 10M17 7L7 17" },
};

export function VerdictBadge({ verdict, size = "md" }: { verdict: V; size?: "sm" | "md" }) {
  const m = META[verdict];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-medium ${size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-[13px]"}`}
      style={{ color: m.color, background: m.bg }}
    >
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" aria-hidden>
        <path d={m.icon} />
      </svg>
      {m.label}
    </span>
  );
}

export function StatusDot({ status }: { status: "ok" | "warn" | "error" | "skip" }) {
  const map = {
    ok: { c: "var(--ok)", d: "M5 12l5 5 9-10", t: "completed" },
    warn: { c: "var(--warn)", d: "M12 7v6M12 17h.01", t: "warning" },
    error: { c: "var(--fail)", d: "M7 7l10 10M17 7L7 17", t: "error" },
    skip: { c: "var(--muted)", d: "M8 12h8", t: "skipped" },
  }[status];
  return (
    <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full" style={{ background: map.c }} title={map.t}>
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="var(--panel)" strokeWidth="3.2" strokeLinecap="round" aria-label={map.t}>
        <path d={map.d} />
      </svg>
    </span>
  );
}
