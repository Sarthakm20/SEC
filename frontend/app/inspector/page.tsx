"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Trace } from "@/components/Trace";
import { VerdictBadge } from "@/components/Verdict";
import { api, type Answer, type Passage, type RunSummary, type Verdict } from "@/lib/api";
import { SECTION_NAMES, ms, pages } from "@/lib/format";
import { isTyping, useKeydown } from "@/lib/hooks";

const STATUS_TEXT: Record<string, { label: string; color: string }> = {
  verified_fact: { label: "Reported fact", color: "var(--ok)" },
  calculated: { label: "Calculated", color: "var(--ok)" },
  interpretation: { label: "Narrative / interpretation", color: "var(--ink-2)" },
  unsupported: { label: "Unsupported", color: "var(--fail)" },
};

const VERDICTS: { id: Verdict | "all"; label: string }[] = [
  { id: "all", label: "All" },
  { id: "verified", label: "Verified" },
  { id: "partially_verified", label: "Partial" },
  { id: "insufficient_evidence", label: "No evidence" },
  { id: "failed", label: "Failed" },
];

export default function InspectorPage() {
  return (
    <Suspense fallback={<p className="text-sm text-[var(--muted)]">Loading…</p>}>
      <Inspector />
    </Suspense>
  );
}

function Inspector() {
  const params = useSearchParams();
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [id, setId] = useState<string | null>(params.get("run"));
  const [run, setRun] = useState<Answer | null>(null);
  const [loadingRun, setLoadingRun] = useState(false);
  const [query, setQuery] = useState("");
  const [verdict, setVerdict] = useState<Verdict | "all">("all");
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api
      .runs(60)
      .then((r) => {
        setRuns(r);
        if (!id && r.length) setId(r[0].run_id);
      })
      .catch(() => setRuns([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setLoadingRun(true);
    api
      .run(id)
      .then((r) => !cancelled && setRun(r))
      .catch(() => !cancelled && setRun(null))
      .finally(() => !cancelled && setLoadingRun(false));
    // keep the URL shareable without adding history entries
    window.history.replaceState(null, "", `/inspector?run=${id}`);
    return () => {
      cancelled = true;
    };
  }, [id]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (runs ?? []).filter((r) => (verdict === "all" || r.verdict === verdict) && (!q || r.question.toLowerCase().includes(q) || r.run_id.includes(q)));
  }, [runs, query, verdict]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: runs?.length ?? 0 };
    (runs ?? []).forEach((r) => (c[r.verdict] = (c[r.verdict] ?? 0) + 1));
    return c;
  }, [runs]);

  // j/k or ↑/↓ move through the visible runs; "/" searches
  useKeydown((e) => {
    if (isTyping(e)) return;
    if (e.key === "/") {
      e.preventDefault();
      searchRef.current?.focus();
      return;
    }
    const down = e.key === "j" || e.key === "ArrowDown";
    const up = e.key === "k" || e.key === "ArrowUp";
    if ((!down && !up) || !visible.length) return;
    e.preventDefault();
    const i = visible.findIndex((r) => r.run_id === id);
    const n = down ? Math.min(i + 1, visible.length - 1) : Math.max(i - 1, 0);
    setId(visible[n].run_id);
    document.getElementById(`run-${visible[n].run_id}`)?.scrollIntoView({ block: "nearest" });
  });

  return (
    <div className="mx-auto grid max-w-7xl grid-cols-1 gap-6 lg:grid-cols-[300px_minmax(0,1fr)]">
      <aside>
        <h1 className="font-serif text-[28px] font-semibold leading-tight">Inspector</h1>
        <p className="text-sm text-[var(--ink-2)]">Observable steps, retrieval scores and verification checks for each answer.</p>

        <input
          ref={searchRef}
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search questions…  ( / )"
          className="field mt-4 w-full text-sm placeholder:text-[var(--muted)]"
          aria-label="Search runs"
        />
        <div className="mt-2 flex flex-wrap gap-1" role="group" aria-label="Filter by verdict">
          {VERDICTS.filter((v) => v.id === "all" || counts[v.id]).map((v) => (
            <button key={v.id} aria-pressed={verdict === v.id} onClick={() => setVerdict(v.id)} className="chip !px-2 !py-0.5 !text-[11px]">
              {v.label} <span className="num opacity-70">{counts[v.id] ?? 0}</span>
            </button>
          ))}
        </div>

        <ul className="mt-3 flex max-h-[68vh] flex-col gap-1 overflow-y-auto pr-1">
          {runs === null && [0, 1, 2, 3, 4].map((i) => <li key={i} className="skeleton h-16" />)}
          {runs?.length === 0 && (
            <li className="text-sm text-[var(--muted)]">
              No questions asked yet.{" "}
              <Link href="/research" className="text-[var(--accent)] hover:underline">
                Use the research assistant first.
              </Link>
            </li>
          )}
          {runs && runs.length > 0 && visible.length === 0 && <li className="px-3 py-4 text-sm text-[var(--muted)]">No runs match.</li>}
          {visible.map((r) => (
            <li key={r.run_id} id={`run-${r.run_id}`}>
              <button
                onClick={() => setId(r.run_id)}
                aria-current={id === r.run_id ? "true" : undefined}
                className={`w-full rounded-lg border-l-2 px-3 py-2 text-left text-sm transition-colors ${
                  id === r.run_id ? "border-[var(--accent)] bg-[var(--accent-soft)]" : "border-transparent hover:bg-[var(--panel-2)]"
                }`}
              >
                <div className="line-clamp-2">{r.question}</div>
                <div className="mt-1 flex items-center gap-2">
                  <VerdictBadge verdict={r.verdict} size="sm" />
                  <span className="num text-xs text-[var(--muted)]">
                    {ms(r.latency_ms)} · {r.experiment}
                  </span>
                </div>
              </button>
            </li>
          ))}
        </ul>
        {visible.length > 1 && (
          <p className="mt-2 text-[11px] text-[var(--muted)]">
            <kbd>j</kbd> <kbd>k</kbd> or <kbd>↑</kbd> <kbd>↓</kbd> to move between runs
          </p>
        )}
      </aside>

      {run ? (
        <div className={`transition-opacity ${loadingRun ? "opacity-50" : ""}`}>
          <RunDetail key={run.run_id} run={run} />
        </div>
      ) : loadingRun ? (
        <div className="flex flex-col gap-4">
          <div className="skeleton h-40" />
          <div className="skeleton h-72" />
        </div>
      ) : (
        <div className="panel p-6 text-sm text-[var(--muted)]">Select a question to inspect it.</div>
      )}
    </div>
  );
}

function RunDetail({ run }: { run: Answer }) {
  const v = run.verification;
  const [copied, setCopied] = useState(false);
  const [claimFilter, setClaimFilter] = useState<string>("all");
  const claimCounts = v.claims.reduce<Record<string, number>>((m, c) => ((m[c.status] = (m[c.status] ?? 0) + 1), m), {});
  const claims = v.claims.filter((c) => claimFilter === "all" || c.status === claimFilter);

  return (
    <div className="stagger flex min-w-0 flex-col gap-6">
      <section className="panel p-5">
        <div className="flex flex-wrap items-center gap-3">
          <VerdictBadge verdict={v.verdict} />
          <span className="num text-xs text-[var(--muted)]">
            run{" "}
            <button
              type="button"
              className="rounded px-1 font-mono hover:bg-[var(--panel-2)] hover:text-[var(--accent)]"
              title="Copy a link to this run"
              onClick={() => {
                navigator.clipboard?.writeText(`${window.location.origin}/inspector?run=${run.run_id}`);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}
            >
              {copied ? "link copied" : run.run_id}
            </button>{" "}
            · pipeline {run.experiment} · {ms(run.latency_ms)}
          </span>
          <Link href={`/research?q=${encodeURIComponent(run.question)}`} className="ml-auto text-xs font-medium text-[var(--accent)] hover:underline">
            Ask again →
          </Link>
        </div>
        <h2 className="mt-2 font-serif text-2xl font-semibold">{run.question}</h2>
        <div className="mt-4 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-[var(--rule)] bg-[var(--rule)] sm:grid-cols-4">
          <Stat label="Citations valid" value={`${v.citations_valid}/${v.citations_total}`} ratio={v.citations_total ? v.citations_valid / v.citations_total : null} />
          <Stat label="Numbers matched" value={`${v.numbers_supported}/${v.numbers_total}`} ratio={v.numbers_total ? v.numbers_supported / v.numbers_total : null} />
          <Stat label="Calculations recomputed" value={String(v.recomputed_calculations)} />
          <Stat label="Cost" value={run.usage.provider === "offline" ? "$0 (no LLM)" : `$${run.usage.estimated_cost_usd.toFixed(4)}`} />
        </div>
        {(v.unsupported_numbers.length > 0 || v.invalid_citations.length > 0) && (
          <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
            {v.unsupported_numbers.map((n) => (
              <span key={`n-${n}`} className="rounded-full bg-[var(--fail-soft)] px-2 py-0.5 text-[var(--fail)]" title="Number in the answer with no matching evidence">
                {n}
              </span>
            ))}
            {v.invalid_citations.map((c) => (
              <span key={`c-${c}`} className="cite cite-bad !align-baseline" title="Citation that matches no retrieved evidence">
                {c}
              </span>
            ))}
          </div>
        )}
      </section>

      <div className="grid grid-cols-1 gap-6 2xl:grid-cols-2">
        <section className="panel p-5">
          <h3 className="font-serif text-lg font-semibold">Execution trace</h3>
          <p className="mb-3 text-xs text-[var(--muted)]">
            Planner: {run.plan.planner} · type {run.plan.query_type.replaceAll("_", " ")} · {run.plan.tickers.join(", ") || "no company"}
            {run.plan.fiscal_years.length ? ` · FY${run.plan.fiscal_years.join(", FY")}` : ""}
          </p>
          <TimingBar events={run.trace} />
          <Trace events={run.trace} />
        </section>

        <section className="panel p-5">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="font-serif text-lg font-semibold">Claim-by-claim verification</h3>
            {v.claims.length > 0 && (
              <div className="flex flex-wrap gap-1" role="group" aria-label="Filter claims">
                <button aria-pressed={claimFilter === "all"} onClick={() => setClaimFilter("all")} className="chip !px-2 !py-0.5 !text-[11px]">
                  All {v.claims.length}
                </button>
                {Object.entries(claimCounts).map(([s, n]) => (
                  <button key={s} aria-pressed={claimFilter === s} onClick={() => setClaimFilter(s)} className="chip !px-2 !py-0.5 !text-[11px]">
                    {STATUS_TEXT[s]?.label ?? s} {n}
                  </button>
                ))}
              </div>
            )}
          </div>
          <ul className="mt-3 flex flex-col gap-2.5">
            {claims.map((c, i) => (
              <Claim key={`${claimFilter}-${i}`} c={c} />
            ))}
            {v.claims.length === 0 && <li className="text-sm text-[var(--muted)]">No claims were extracted from this answer.</li>}
          </ul>
          {(v.conflicts.length > 0 || v.period_issues.length > 0) && (
            <div className="mt-4 rounded-lg bg-[var(--warn-soft)] p-3 text-xs">
              {[...v.period_issues, ...v.conflicts].slice(0, 6).map((x, i) => (
                <p key={i}>{x}</p>
              ))}
            </div>
          )}
        </section>
      </div>

      {run.passages.length > 0 && <PassageTable passages={run.passages} />}

      {run.calculations.length > 0 && (
        <section className="panel overflow-x-auto p-5">
          <h3 className="font-serif text-lg font-semibold">Calculation log</h3>
          <table className="data mt-3">
            <thead>
              <tr>
                <th>Id</th>
                <th>Metric</th>
                <th>Formula</th>
                <th>Inputs</th>
                <th className="r">Result</th>
              </tr>
            </thead>
            <tbody>
              {run.calculations.map((c) => (
                <tr key={c.id}>
                  <td>
                    <span className="cite cite-C !align-baseline">{c.evidence_id}</span>
                  </td>
                  <td>
                    {c.ticker} FY{c.fiscal_year} · {c.label}
                  </td>
                  <td>
                    <code className="text-xs">{c.formula}</code>
                  </td>
                  <td className="num text-xs text-[var(--ink-2)]">
                    {c.inputs.map((i) => (
                      <div key={i.name}>
                        {i.name} = {i.value} {i.evidence_id ? `(${i.evidence_id})` : ""}
                      </div>
                    ))}
                  </td>
                  <td className="r num font-medium">{c.display}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}

function Claim({ c }: { c: Answer["verification"]["claims"][number] }) {
  const [open, setOpen] = useState(false);
  const meta = STATUS_TEXT[c.status];
  const hasMore = c.sentence.length > 220 || c.citations.length > 0 || c.numbers.length > 0;
  return (
    <li className="rise border-l-2 pl-3" style={{ borderColor: meta.color }}>
      <button type="button" className="w-full text-left" onClick={() => hasMore && setOpen((o) => !o)} aria-expanded={hasMore ? open : undefined}>
        <div className="text-xs font-semibold" style={{ color: meta.color }}>
          {meta.label}
          {c.support_score !== null && <span className="num font-normal text-[var(--muted)]"> · support {c.support_score.toFixed(2)}</span>}
          {hasMore && <span className="ml-1 font-normal text-[var(--muted)]">{open ? "▴" : "▾"}</span>}
        </div>
        <div className={`text-sm ${open ? "" : "line-clamp-3"}`}>{c.sentence}</div>
      </button>
      {open && (c.citations.length > 0 || c.numbers.length > 0) && (
        <div className="mt-1 flex flex-wrap items-center gap-1 text-xs">
          {c.citations.map((id) => (
            <span key={id} className={`cite cite-${id[0]} !m-0 !align-baseline`}>
              {id}
            </span>
          ))}
          {c.numbers.map((n) => (
            <span key={n} className="num rounded bg-[var(--panel-2)] px-1.5 text-[var(--ink-2)]">
              {n}
            </span>
          ))}
        </div>
      )}
      {c.issues.length > 0 && <div className="text-xs text-[var(--warn)]">{c.issues.join("; ")}</div>}
    </li>
  );
}

/** Where the time went: each traced step as a proportional segment. */
function TimingBar({ events }: { events: Answer["trace"] }) {
  const timed = events.filter((e) => e.duration_ms > 0);
  const total = timed.reduce((s, e) => s + e.duration_ms, 0);
  const [hover, setHover] = useState<number | null>(null);
  if (!timed.length || !total) return null;
  const tone = (s: string) => (s === "error" ? "var(--fail)" : s === "warn" ? "var(--warn)" : "var(--accent)");
  return (
    <div className="mb-4">
      <div className="flex h-2.5 overflow-hidden rounded-full bg-[var(--panel-2)]" onPointerLeave={() => setHover(null)}>
        {timed.map((e, i) => (
          <div
            key={i}
            onPointerEnter={() => setHover(i)}
            className="h-full border-r border-[var(--panel)] transition-opacity last:border-r-0"
            style={{ width: `${(e.duration_ms / total) * 100}%`, background: tone(e.status), opacity: hover === null || hover === i ? 1 - (i % 2) * 0.35 : 0.25 }}
          />
        ))}
      </div>
      <div className="num mt-1 h-4 text-[11px] text-[var(--muted)]">
        {hover !== null ? (
          <>
            <span className="text-[var(--ink)]">{timed[hover].label}</span> · {ms(timed[hover].duration_ms)} ({((timed[hover].duration_ms / total) * 100).toFixed(0)}%)
          </>
        ) : (
          <>Total {ms(total)} across {timed.length} timed steps. Hover the bar for a breakdown.</>
        )}
      </div>
    </div>
  );
}

type SortKey = "order" | "bm25" | "dense" | "rrf" | "rerank";

function PassageTable({ passages }: { passages: Passage[] }) {
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "order", dir: 1 });
  const [open, setOpen] = useState<string | null>(null);

  const val = (p: Passage, k: SortKey): number | null => {
    const s = p.scores;
    if (k === "bm25") return s.bm25_rank;
    if (k === "dense") return s.dense_rank;
    if (k === "rrf") return s.rrf_score;
    if (k === "rerank") return s.rerank_score;
    return null;
  };
  const rows = useMemo(() => {
    if (sort.key === "order") return sort.dir === 1 ? passages : [...passages].reverse();
    return [...passages].sort((a, b) => {
      const x = val(a, sort.key);
      const y = val(b, sort.key);
      if (x === null && y === null) return 0;
      if (x === null) return 1; // missing scores always last
      if (y === null) return -1;
      return (x - y) * sort.dir;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [passages, sort]);

  // ranks read best-first ascending; scores read best-first descending
  const defaultDir = (k: SortKey): 1 | -1 => (k === "rrf" || k === "rerank" ? -1 : 1);
  const head = (k: SortKey, label: string, title: string) => (
    <th
      className="r sortable"
      title={title}
      aria-sort={sort.key === k ? (sort.dir === 1 ? "ascending" : "descending") : "none"}
      onClick={() => setSort((s) => (s.key === k ? { key: k, dir: (s.dir * -1) as 1 | -1 } : { key: k, dir: defaultDir(k) }))}
    >
      {label}
      <span className="ml-0.5 text-[10px]">{sort.key === k ? (sort.dir === 1 ? "▲" : "▼") : "↕"}</span>
    </th>
  );

  return (
    <section className="panel overflow-x-auto p-5">
      <h3 className="font-serif text-lg font-semibold">Retrieved passages</h3>
      <p className="text-xs text-[var(--muted)]">
        Ranks from BM25 and dense search are fused with reciprocal rank fusion, then reranked by a cross-encoder. Relevance is not the same as correctness. Click a column to sort, a row to read the passage.
      </p>
      <table className="data mt-3">
        <thead>
          <tr>
            <th className="sortable" onClick={() => setSort((s) => ({ key: "order", dir: s.key === "order" ? ((s.dir * -1) as 1 | -1) : 1 }))}>
              Id <span className="text-[10px]">{sort.key === "order" ? (sort.dir === 1 ? "▲" : "▼") : "↕"}</span>
            </th>
            <th>Source</th>
            {head("bm25", "BM25", "Rank in keyword search (1 = best)")}
            {head("dense", "Dense", "Rank in vector search (1 = best)")}
            {head("rrf", "RRF", "Reciprocal rank fusion score (higher = better)")}
            {head("rerank", "Rerank", "Cross-encoder relevance (higher = better)")}
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => {
            const isOpen = open === p.chunk.id;
            const pg = pages(p.chunk.page_start, p.chunk.page_end);
            return (
              <PassageRow key={p.chunk.id} p={p} pg={pg} isOpen={isOpen} onToggle={() => setOpen(isOpen ? null : p.chunk.id)} maxRerank={Math.max(...passages.map((x) => x.scores.rerank_score ?? 0))} />
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function PassageRow({ p, pg, isOpen, onToggle, maxRerank }: { p: Passage; pg: string | null; isOpen: boolean; onToggle: () => void; maxRerank: number }) {
  const rr = p.scores.rerank_score;
  return (
    <>
      <tr
        className="row-click"
        onClick={onToggle}
        tabIndex={0}
        aria-expanded={isOpen}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onToggle();
          }
        }}
      >
        <td>
          <span className="cite cite-S !align-baseline">{p.evidence_id}</span>
        </td>
        <td className="max-w-md">
          <div className="text-sm">
            {p.chunk.ticker} FY{p.chunk.fiscal_year} · {SECTION_NAMES[p.chunk.section] ?? p.chunk.section} {pg ? `· ${pg}` : ""}
          </div>
          <div className="line-clamp-1 text-xs text-[var(--muted)]">{p.chunk.subsection ?? p.chunk.text.slice(0, 120)}</div>
        </td>
        <td className="r num">{p.scores.bm25_rank ?? "—"}</td>
        <td className="r num">{p.scores.dense_rank ?? "—"}</td>
        <td className="r num">{p.scores.rrf_score?.toFixed(4) ?? "—"}</td>
        <td className="r num">
          {rr !== null ? (
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block h-1.5 w-10 overflow-hidden rounded-full bg-[var(--panel-2)]" aria-hidden>
                <span className="block h-full rounded-full bg-[var(--accent)]" style={{ width: `${maxRerank > 0 ? Math.max(0, (rr / maxRerank) * 100) : 0}%` }} />
              </span>
              {rr.toFixed(2)}
            </span>
          ) : (
            "—"
          )}
        </td>
      </tr>
      {isOpen && (
        <tr>
          <td colSpan={6} className="!pt-0">
            <div className="rise inset p-3">
              <p className="whitespace-pre-line text-[13px] leading-relaxed">{p.chunk.text}</p>
              <div className="mt-2 flex flex-wrap gap-3 text-xs text-[var(--muted)]">
                <span>{p.chunk.kind === "table" ? "Table chunk" : "Text chunk"}</span>
                {p.chunk.injection_flags.length > 0 && <span className="text-[var(--warn)]">flagged: {p.chunk.injection_flags.join(", ")}</span>}
                {p.chunk.source_url && (
                  <a href={p.chunk.source_url} target="_blank" rel="noopener noreferrer" className="font-medium text-[var(--accent)] hover:underline" onClick={(e) => e.stopPropagation()}>
                    View source ↗
                  </a>
                )}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function Stat({ label, value, ratio = null }: { label: string; value: string; ratio?: number | null }) {
  const color = ratio === null ? undefined : ratio >= 1 ? "var(--ok)" : ratio >= 0.5 ? "var(--warn)" : "var(--fail)";
  return (
    <div className="bg-[var(--panel)] px-4 py-3">
      <div className="text-xs text-[var(--muted)]">{label}</div>
      <div className="num text-lg font-semibold">{value}</div>
      {ratio !== null && (
        <div className="mt-1 h-1 overflow-hidden rounded-full bg-[var(--panel-2)]">
          <div className="h-full rounded-full transition-all duration-700" style={{ width: `${Math.min(100, ratio * 100)}%`, background: color }} />
        </div>
      )}
    </div>
  );
}
