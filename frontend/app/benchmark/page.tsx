"use client";

import { useEffect, useState } from "react";
import { PipelineBars } from "@/components/Charts";
import { api, ApiError, type BenchmarkReport, type GoldCrosscheck } from "@/lib/api";
import { useDismiss } from "@/lib/hooks";

type Col = { key: string; label: string; fmt?: "pct" | "ms" | "usd"; better: "high" | "low" };

const CATEGORY_LABELS: Record<string, string> = {
  direct_lookup: "Direct lookup",
  cross_year: "Cross-year change",
  ratio: "Financial ratios",
  cross_company: "Cross-company comparison",
  trend: "Multi-year trend",
  narrative: "Narrative & MD&A",
  footnote: "Financial footnote",
  multi_hop: "Multi-hop reasoning",
  unanswerable: "Out of scope / Abstentions",
};

const HEADLINE_METRICS = [
  { key: "exact_match", label: "Numeric exact match" },
  { key: "task_success", label: "Task success" },
  { key: "abstention_accuracy", label: "Correct abstentions" },
  { key: "latency_p50_ms", label: "Median latency" },
];

export default function BenchmarkPage() {
  const [report, setReport] = useState<BenchmarkReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState<string>("task_success");
  const [selected, setSelected] = useState<string | null>(null);
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);

  useEffect(() => {
    api
      .evalLatest()
      .then(setReport)
      .catch((e) => setError(e.message));
  }, []);

  if (error)
    return (
      <div className="mx-auto max-w-3xl panel p-6">
        <h1 className="font-serif text-2xl font-semibold">No benchmark results yet</h1>
        <p className="mt-2 text-sm text-[var(--ink-2)]">
          Run <code>python -m evaluation.run_benchmark</code> from <code>backend/</code>. Results appear here when it finishes.
        </p>
      </div>
    );
  if (!report)
    return (
      <div className="mx-auto max-w-6xl" aria-busy="true" aria-label="Loading benchmark results">
        <div className="skeleton h-10 w-[28rem] max-w-full" />
        <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="skeleton h-24" />
          ))}
        </div>
        <div className="skeleton mt-8 h-72" />
      </div>
    );

  const k = report.k;
  const cols: Col[] = [
    { key: `hit@${k}`, label: `Hit@${k}`, fmt: "pct", better: "high" },
    { key: "mrr", label: "MRR", better: "high" },
    { key: `ndcg@${k}`, label: `nDCG@${k}`, better: "high" },
    { key: "exact_match", label: "Numeric exact match", fmt: "pct", better: "high" },
    { key: "citation_precision", label: "Citation precision", fmt: "pct", better: "high" },
    { key: "faithfulness", label: "Faithfulness", fmt: "pct", better: "high" },
    { key: "abstention_accuracy", label: "Correct abstentions", fmt: "pct", better: "high" },
    { key: "task_success", label: "Task success", fmt: "pct", better: "high" },
    { key: "latency_p50_ms", label: "Median latency", fmt: "ms", better: "low" },
  ];

  const allExps = Object.entries(report.experiments);
  const exps = sort
    ? [...allExps].sort(([, a], [, b]) => {
        const x = a.summary[sort.key];
        const y = b.summary[sort.key];
        if (typeof x !== "number" && typeof y !== "number") return 0;
        if (typeof x !== "number") return 1;
        if (typeof y !== "number") return -1;
        return (x - y) * sort.dir;
      })
    : allExps;
  const best: Record<string, number> = {};
  for (const c of cols) {
    const vals = exps.map(([, e]) => e.summary[c.key]).filter((v): v is number => typeof v === "number");
    if (vals.length) best[c.key] = c.better === "high" ? Math.max(...vals) : Math.min(...vals);
  }

  const show = (v: unknown, f?: Col["fmt"]) => {
    if (typeof v !== "number") return "—";
    if (f === "pct") return `${(v * 100).toFixed(1)}%`;
    if (f === "ms") return v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`;
    return v.toFixed(3);
  };

  // Headline cards: the full pipeline (E, else the last one listed) against the first-listed baseline (A).
  const headline = allExps.find(([id]) => id === "E") ?? allExps[allExps.length - 1];
  const baseline = allExps[0];

  // Extract categories present in first experiment
  const firstExp = exps[0]?.[1]?.summary as any;
  const categoryKeys = firstExp?.by_category ? Object.keys(firstExp.by_category) : [];

  return (
    <div className="mx-auto max-w-6xl pb-12">
      {/* Page Header */}
      <div className="border-b border-[var(--rule)] pb-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="font-serif text-[32px] font-semibold leading-tight">Benchmark & Architecture Ablation</h1>
            <p className="mt-1 text-sm text-[var(--ink-2)]">
              Rigorous {report.questions}-question gold evaluation across Apple, Microsoft and NVIDIA 10-K filings.
            </p>
          </div>
          <GoldBadge />
        </div>
        <p className="num mt-2 text-xs text-[var(--muted)]">
          Run {new Date(report.created_at).toLocaleString()} · Answers by{" "}
          {report.llm.provider === "offline"
            ? "Deterministic Synthesis ($0)"
            : `${report.llm.provider}/${report.llm.model}`}{" "}
          · Embeddings {report.embedding} · Reranker {report.reranker ?? "none"} · {report.corpus_chunks.toLocaleString()} chunks
        </p>
      </div>

      {/* KPI Highlight Cards — computed from the latest report: headline pipeline vs the baseline */}
      {headline && (
        <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
          {HEADLINE_METRICS.map((m) => {
            const col = cols.find((c) => c.key === m.key)!;
            const v = headline[1].summary[m.key];
            const b = baseline && baseline[0] !== headline[0] ? baseline[1].summary[m.key] : undefined;
            const both = typeof v === "number" && typeof b === "number";
            const better = both && (col.better === "high" ? v > b : v < b);
            const worse = both && (col.better === "high" ? v < b : v > b);
            return (
              <button
                key={m.key}
                type="button"
                onClick={() => {
                  setMetric(m.key);
                  setSelected(headline[0]);
                  document.getElementById("metric-explorer")?.scrollIntoView({ behavior: "smooth", block: "start" });
                }}
                className={`panel p-4 text-left transition-all hover:-translate-y-px hover:shadow-md ${metric === m.key ? "border-[var(--accent)]" : ""}`}
                title={`Explore ${col.label} across all pipelines`}
              >
                <div className="text-xs font-medium text-[var(--muted)]">
                  {m.label} ({headline[0]})
                </div>
                <div
                  className="num mt-1 text-2xl font-bold"
                  style={{ color: better ? "var(--ok)" : worse ? "var(--fail)" : "var(--ink)" }}
                >
                  {show(v, col.fmt)}
                </div>
                <div className="num mt-1 text-[11px] text-[var(--ink-2)]">
                  {typeof b === "number" ? `vs ${show(b, col.fmt)} for baseline ${baseline![0]}` : "No baseline to compare"}
                </div>
              </button>
            );
          })}
        </div>
      )}

      {/* Metric explorer */}
      <MetricExplorer
        cols={cols}
        exps={allExps}
        metric={metric}
        setMetric={setMetric}
        selected={selected}
        setSelected={setSelected}
        show={show}
      />

      {/* Main Ablation Table */}
      <div className="mt-8">
        <h2 className="font-serif text-xl font-semibold">End-to-End Pipeline Ablation</h2>
        <p className="text-xs text-[var(--muted)]">
          Progressively adding components from dense baseline (A) to full verifiable agent (E).
        </p>

        <section className="panel mt-3 overflow-x-auto p-2 shadow-sm">
          <table className="data">
            <thead>
              <tr>
                <th className="sortable min-w-56" onClick={() => setSort(null)} title="Restore pipeline order">
                  Pipeline {sort === null && <span className="text-[10px]">▲</span>}
                </th>
                {cols.map((c) => {
                  const on = sort?.key === c.key;
                  return (
                    <th
                      key={c.key}
                      className={`r sortable ${metric === c.key ? "!text-[var(--accent)]" : ""}`}
                      aria-sort={on ? (sort!.dir === 1 ? "ascending" : "descending") : "none"}
                      title={`Sort by ${c.label} (${c.better === "high" ? "higher" : "lower"} is better)`}
                      onClick={() => {
                        setMetric(c.key);
                        const bestFirst: 1 | -1 = c.better === "high" ? -1 : 1;
                        setSort((s) => (s?.key === c.key ? { key: c.key, dir: (s.dir * -1) as 1 | -1 } : { key: c.key, dir: bestFirst }));
                      }}
                    >
                      {c.label}
                      <span className="ml-0.5 text-[10px]">{on ? (sort!.dir === 1 ? "▲" : "▼") : ""}</span>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {exps.map(([id, e]) => (
                <tr
                  key={id}
                  className={`row-click transition-colors ${selected === id ? "bg-[var(--accent-soft)]" : ""}`}
                  onClick={() => setSelected((s) => (s === id ? null : id))}
                  aria-selected={selected === id}
                >
                  <td className="min-w-56">
                    <div className="flex items-center gap-2">
                      <span className="grid h-5 w-5 place-items-center rounded bg-[var(--ink)] text-xs font-bold text-[var(--panel)]">
                        {id}
                      </span>
                      <span className="font-semibold">{e.description}</span>
                    </div>
                    {e.reader && <div className="mt-0.5 text-[11px] text-[var(--muted)]">Reader: {e.reader}</div>}
                  </td>
                  {cols.map((c) => {
                    const v = e.summary[c.key];
                    const isBest =
                      typeof v === "number" &&
                      best[c.key] === v &&
                      exps.filter(([, x]) => typeof x.summary[c.key] === "number").length > 1;
                    return (
                      <td
                        key={c.key}
                        className={`r num ${isBest ? "font-bold text-[var(--ok)]" : ""} ${
                          typeof v !== "number" ? "text-[var(--muted)]" : ""
                        }`}
                      >
                        {show(v, c.fmt)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>

      {/* Category Breakdown Table (as featured in the blueprint) */}
      {categoryKeys.length > 0 && (
        <div className="mt-10">
          <h2 className="font-serif text-xl font-semibold">Task Success by Category</h2>
          <p className="text-xs text-[var(--muted)]">
            Shows exactly where text-only RAG baselines fail (ratios, trends, multi-company) and where structured XBRL shines.
          </p>

          <section className="panel mt-3 overflow-x-auto p-2 shadow-sm">
            <table className="data">
              <thead>
                <tr>
                  <th>Category</th>
                  <th className="r">Questions (N)</th>
                  {allExps.map(([id]) => (
                    <th key={id} className={`r text-center w-28 ${selected === id ? "!text-[var(--accent)]" : ""}`}>
                      Pipeline {id}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {categoryKeys.map((catKey) => {
                  const n = (firstExp.by_category[catKey] as any)?.n ?? 0;
                  return (
                    <tr key={catKey} className="hover:bg-[var(--panel-2)] transition-colors">
                      <td className="font-medium text-[var(--ink)]">
                        {CATEGORY_LABELS[catKey] ?? catKey.replaceAll("_", " ")}
                      </td>
                      <td className="r num text-[var(--muted)]">{n}</td>
                      {allExps.map(([id, exp]) => {
                        const catData = (exp.summary as any)?.by_category?.[catKey];
                        const score = catData?.task_success;
                        const scorePct = typeof score === "number" ? score * 100 : null;
                        const isHigh = scorePct !== null && scorePct >= 99;
                        const isZero = scorePct !== null && scorePct === 0;
                        // heat tint: fail-soft at 0% blending to ok-soft at 100%
                        const tint =
                          scorePct === null
                            ? undefined
                            : `color-mix(in oklab, var(--ok-soft) ${scorePct}%, var(--fail-soft))`;

                        return (
                          <td
                            key={id}
                            className={`r num text-center transition-shadow ${selected === id ? "shadow-[inset_0_0_0_2px_var(--accent)]" : ""}`}
                            style={{ background: tint }}
                            title={scorePct !== null ? `Pipeline ${id}: ${scorePct.toFixed(1)}% task success on ${n} questions` : undefined}
                          >
                            {scorePct !== null ? (
                              <div className="inline-flex items-center gap-1.5">
                                <span
                                  className={`font-semibold ${
                                    isHigh
                                      ? "text-[var(--ok)]"
                                      : isZero
                                      ? "text-[var(--fail)]"
                                      : "text-[var(--ink-2)]"
                                  }`}
                                >
                                  {scorePct.toFixed(0)}%
                                </span>
                              </div>
                            ) : (
                              <span className="text-[var(--muted)]">—</span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        </div>
      )}

      {/* Explanatory Takeaway Notes */}
      <div className="panel mt-10 p-5 bg-[var(--panel-2)]">
        <h3 className="font-semibold text-sm">Key Evaluation Takeaways</h3>
        <Takeaways exps={allExps} />
        <p className="mt-3 text-[10px] text-[var(--muted)]">Figures computed from this benchmark run. Pipelines whose description mentions XBRL count as structured; the rest as text-only.</p>
      </div>
    </div>
  );
}

function MetricExplorer({
  cols,
  exps,
  metric,
  setMetric,
  selected,
  setSelected,
  show,
}: {
  cols: Col[];
  exps: [string, BenchmarkReport["experiments"][string]][];
  metric: string;
  setMetric: (k: string) => void;
  selected: string | null;
  setSelected: (id: string | null) => void;
  show: (v: unknown, f?: Col["fmt"]) => string;
}) {
  const col = cols.find((c) => c.key === metric) ?? cols[0];
  const data = exps
    .map(([id, e]) => ({ id, value: e.summary[col.key] }))
    .filter((d): d is { id: string; value: number } => typeof d.value === "number");
  const fmt = (v: number) => show(v, col.fmt);
  const sel = selected ? data.find((d) => d.id === selected) : undefined;
  const base = data[0];
  const delta = sel && base && sel.id !== base.id ? sel.value - base.value : null;

  return (
    <section id="metric-explorer" className="panel mt-8 scroll-mt-6 p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="font-serif text-xl font-semibold">Explore a metric</h2>
          <p className="text-xs text-[var(--muted)]">Pick a metric, then click a bar or a table row to compare that pipeline with the baseline.</p>
        </div>
        <span className="text-xs text-[var(--muted)]">{col.better === "high" ? "Higher is better" : "Lower is better"}</span>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5" role="tablist" aria-label="Metric">
        {cols.map((c) => (
          <button key={c.key} role="tab" aria-selected={metric === c.key} onClick={() => setMetric(c.key)} className="chip !py-1 !text-[11px]">
            {c.label}
          </button>
        ))}
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-[1fr_220px]">
        {data.length ? (
          <PipelineBars data={data} fmt={fmt} label={col.label} selected={selected} onSelect={(id) => setSelected(selected === id ? null : id)} />
        ) : (
          <p className="py-16 text-center text-sm text-[var(--muted)]">No pipeline reported this metric.</p>
        )}
        <div className="inset flex flex-col justify-center p-4 text-sm">
          {sel ? (
            <>
              <div className="text-xs text-[var(--muted)]">Pipeline {sel.id}</div>
              <div className="num text-2xl font-semibold">{fmt(sel.value)}</div>
              {delta !== null && base && (
                <div
                  className="num mt-1 text-xs"
                  style={{ color: (col.better === "high" ? delta >= 0 : delta <= 0) ? "var(--ok)" : "var(--fail)" }}
                >
                  {delta >= 0 ? "+" : "−"}
                  {col.fmt === "pct" ? `${Math.abs(delta * 100).toFixed(1)} pts` : col.fmt === "ms" ? fmt(Math.abs(delta)) : Math.abs(delta).toFixed(3)} vs pipeline {base.id}
                </div>
              )}
              <button className="mt-3 self-start text-xs font-medium text-[var(--accent)] hover:underline" onClick={() => setSelected(null)}>
                Clear selection
              </button>
            </>
          ) : (
            <p className="text-xs text-[var(--muted)]">Select a pipeline to see how far it moves {col.label.toLowerCase()} from the baseline.</p>
          )}
        </div>
      </div>
    </section>
  );
}

type Exp = [string, BenchmarkReport["experiments"][string]];

const pctText = (v: number) => `${(v * 100).toFixed(1)}%`;

/** "16.7% to 25.0%" for a spread, or a single value when every pipeline agrees. */
function rangeText(vals: number[]): string {
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  return lo === hi ? pctText(lo) : `${pctText(lo)} to ${pctText(hi)}`;
}

function nums(exps: Exp[], key: string): number[] {
  return exps.map(([, e]) => e.summary[key]).filter((v): v is number => typeof v === "number");
}

/** Narrative takeaways whose numbers come from the report, so they stay true after every rerun. */
function Takeaways({ exps }: { exps: Exp[] }) {
  // pipelines that read SEC XBRL facts vs pipelines that only retrieve filing text
  const structured = exps.filter(([, e]) => /xbrl/i.test(e.description));
  const textOnly = exps.filter(([, e]) => !/xbrl/i.test(e.description));
  const ids = (xs: Exp[]) => xs.map(([id]) => id).join(", ");
  const items: React.ReactNode[] = [];

  const emText = nums(textOnly, "exact_match");
  const emStruct = nums(structured, "exact_match");
  if (emText.length && emStruct.length) {
    const gain = Math.min(...emStruct) > Math.max(...emText);
    items.push(
      <li key="em">
        <strong>{gain ? "Structured data is the game changer:" : "Structured data vs text-only retrieval:"}</strong> Text-only RAG ({ids(textOnly)}) gets{" "}
        {gain ? "only " : ""}
        {rangeText(emText)} of numeric questions exactly right. With XBRL facts and Decimal engine calculations ({ids(structured)}), exact match is{" "}
        {rangeText(emStruct)}.
      </li>
    );
  }

  const abText = nums(textOnly, "abstention_accuracy");
  const abStruct = nums(structured, "abstention_accuracy");
  if (abText.length && abStruct.length) {
    const perfect = Math.min(...abStruct) === 1;
    items.push(
      <li key="ab">
        <strong>{perfect ? "Zero hallucination through strict abstention:" : "Abstention on out-of-scope questions:"}</strong> Text-only RAG correctly declines only{" "}
        {rangeText(abText)} of questions it cannot answer, such as unindexed companies (e.g. Tesla) or stock prices, and answers the rest anyway. The verification-first
        layer achieves {rangeText(abStruct)} correct abstentions.
      </li>
    );
  }

  const d = exps.find(([id]) => id === "D")?.[1].summary as any;
  const e = exps.find(([id]) => id === "E")?.[1].summary as any;
  const nd = d?.by_category?.narrative?.task_success;
  const ne = e?.by_category?.narrative?.task_success;
  if (typeof nd === "number" && typeof ne === "number") {
    const verb = ne > nd ? "raising" : ne < nd ? "lowering" : "keeping";
    items.push(
      <li key="nar">
        <strong>Query expansion & sufficiency check (E vs D):</strong> In Pipeline E, the LangGraph sufficiency loop detects when initial retrieval for complex narrative
        queries is weak and performs expansion, {verb} narrative question success{" "}
        {ne === nd ? `at ${pctText(ne)}` : `from ${pctText(nd)} to ${pctText(ne)}`} compared with Pipeline D.
      </li>
    );
  }

  if (!items.length) return <p className="mt-2 text-xs text-[var(--muted)]">This run does not include the pipelines needed for these comparisons.</p>;
  return <ul className="mt-2 list-disc space-y-1.5 pl-5 text-xs leading-relaxed text-[var(--ink-2)]">{items}</ul>;
}

/**
 * Gold-set integrity badge, read from the last `python -m evaluation.crosscheck_gold` run.
 * Click it for what the check means, when it ran, and any values that failed to match.
 */
function GoldBadge() {
  const [gold, setGold] = useState<GoldCrosscheck | null>(null);
  const [state, setState] = useState<"loading" | "missing" | "error" | "ok">("loading");
  const [open, setOpen] = useState(false);
  const ref = useDismiss<HTMLDivElement>(open, () => setOpen(false));

  useEffect(() => {
    api
      .evalGold()
      .then((g) => {
        setGold(g);
        setState("ok");
      })
      .catch((e) => setState(e instanceof ApiError && e.status === 404 ? "missing" : "error"));
  }, []);

  if (state === "loading") return <span className="skeleton h-6 w-56 !rounded-full" aria-hidden />;

  const tone =
    state !== "ok" || !gold
      ? { fg: "var(--none)", bg: "var(--none-soft)", text: state === "missing" ? "Gold set not cross-checked yet" : "Gold-set check unavailable" }
      : gold.mismatched > 0
      ? { fg: "var(--fail)", bg: "var(--fail-soft)", text: `${gold.mismatched} gold value${gold.mismatched === 1 ? "" : "s"} don't match XBRL` }
      : gold.stale
      ? { fg: "var(--warn)", bg: "var(--warn-soft)", text: `Gold set changed since last check (${gold.matched}/${gold.reported_checked})` }
      : { fg: "var(--ok)", bg: "var(--ok-soft)", text: `Verified gold set (${gold.matched}/${gold.reported_checked} XBRL matches)` };

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="rounded-full px-3 py-1 text-xs font-semibold transition-shadow hover:shadow-sm"
        style={{ color: tone.fg, background: tone.bg }}
      >
        {tone.text} <span className="font-normal opacity-70">ⓘ</span>
      </button>
      {open && (
        <div className="popover pop absolute right-0 top-full z-40 mt-2 w-80 p-4 text-xs leading-relaxed text-[var(--ink-2)]">
          <div className="font-semibold text-[var(--ink)]">What this checks</div>
          <p className="mt-1">
            The benchmark grades answers against hand-written gold values. This check makes sure those gold values themselves are right: every reported dollar or per-share
            figure in the gold set is looked up among the company&apos;s actual SEC XBRL facts for that fiscal year and must match exactly. It runs independently of the QA
            pipeline, so the system is never graded against its own numbers.
          </p>
          {gold ? (
            <>
              <dl className="num mt-3 grid grid-cols-[1fr_auto] gap-x-3 gap-y-0.5">
                <dt>Reported values matched</dt>
                <dd className="font-medium text-[var(--ink)]">
                  {gold.matched}/{gold.reported_checked}
                </dd>
                <dt>Derived values (ratios, %)</dt>
                <dd className="font-medium text-[var(--ink)]">{gold.derived_for_review}</dd>
                <dt>Questions in gold set</dt>
                <dd className="font-medium text-[var(--ink)]">{gold.questions}</dd>
                <dt>Checked</dt>
                <dd className="font-medium text-[var(--ink)]">{new Date(gold.created_at).toLocaleString()}</dd>
              </dl>
              <p className="mt-2">Derived values are computed with a formula rather than reported, so they are listed for a person to review instead of being matched.</p>
              {gold.mismatches.length > 0 && (
                <ul className="mt-2 space-y-0.5 text-[var(--fail)]">
                  {gold.mismatches.slice(0, 6).map((m, i) => (
                    <li key={i}>
                      {m.question_id}: {m.label} = {m.value} not found
                    </li>
                  ))}
                </ul>
              )}
              {gold.stale && <p className="mt-2 text-[var(--warn)]">The gold file was edited after this check, so these numbers may be out of date.</p>}
            </>
          ) : (
            <p className="mt-2">{state === "missing" ? "No cross-check result has been saved yet." : "The backend could not return the cross-check result."}</p>
          )}
          {(state !== "ok" || gold?.stale || (gold && gold.mismatched > 0)) && (
            <p className="mt-2">
              Run <code>python -m evaluation.crosscheck_gold</code> from <code>backend/</code> to refresh it.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
