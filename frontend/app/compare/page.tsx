"use client";

import { useEffect, useMemo, useState } from "react";
import { CompareBars } from "@/components/Charts";
import { api, type Comparison, type Company, type MetricValue } from "@/lib/api";
import { factValue, seriesVar } from "@/lib/format";
import { isTyping, useKeydown } from "@/lib/hooks";

const PERCENT = new Set(["revenue_growth", "gross_margin", "operating_margin", "net_margin", "rd_intensity"]);
const USD = new Set(["revenue", "free_cash_flow", "net_income", "operating_cash_flow"]);

export default function ComparePage() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [fy, setFy] = useState<number>(2025);
  const [align, setAlign] = useState<"fiscal" | "calendar">("fiscal");
  const [data, setData] = useState<Comparison | null>(null);
  const [chartMetric, setChartMetric] = useState("operating_margin");
  const [filterQuery, setFilterQuery] = useState("");
  const [focusCell, setFocusCell] = useState<{ metric: string; ticker: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .companies()
      .then((cs) => {
        setCompanies(cs);
        setPicked(cs.map((c) => c.ticker));
        const common = Math.min(...cs.map((c) => Math.max(...c.years.filings)));
        if (Number.isFinite(common)) setFy(common);
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!picked.length) return setData(null);
    api
      .compare(picked, fy, align)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [picked, fy, align]);

  const years = useMemo(() => {
    const all = new Set<number>();
    companies.forEach((c) => c.years.facts.slice(-6).forEach((y) => all.add(y)));
    return Array.from(all).sort((a, b) => b - a);
  }, [companies]);

  const filteredRows = useMemo(() => {
    if (!data?.rows) return [];
    if (!filterQuery.trim()) return data.rows;
    const q = filterQuery.toLowerCase();
    return data.rows.filter(
      (r) => r.label.toLowerCase().includes(q) || r.metric.toLowerCase().includes(q)
    );
  }, [data?.rows, filterQuery]);

  // ↑/↓ step the charted metric through the visible rows
  useKeydown((e) => {
    if (isTyping(e) || (e.key !== "ArrowDown" && e.key !== "ArrowUp") || !filteredRows.length) return;
    e.preventDefault();
    const i = filteredRows.findIndex((r) => r.metric === chartMetric);
    const n = e.key === "ArrowDown" ? Math.min(i + 1, filteredRows.length - 1) : Math.max(i - 1, 0);
    setChartMetric(filteredRows[n].metric);
    setFocusCell(null);
    document.getElementById(`row-${filteredRows[n].metric}`)?.scrollIntoView({ block: "nearest" });
  });

  const chartRow = data?.rows.find((r) => r.metric === chartMetric);
  const focused = focusCell && chartRow?.metric === focusCell.metric ? chartRow.values[focusCell.ticker] : undefined;
  const chartData = chartRow
    ? picked
        .filter((t) => chartRow.values[t]?.value !== null && chartRow.values[t]?.value !== undefined)
        .map((t) => ({ ticker: t, value: Number(chartRow.values[t].value) }))
    : [];

  const exportCSV = () => {
    if (!data) return;
    const headers = ["Metric", ...picked.map((t) => `${t} (FY${data.resolved_fiscal_years[t] || fy})`)];
    const rows = data.rows.map((r) => [
      `"${r.label}"`,
      ...picked.map((t) => `"${r.values[t]?.display ?? ""}"`),
    ]);
    const csvContent = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `sec-financial-comparison-${fy}-${align}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="mx-auto max-w-6xl pb-12">
      <div className="border-b border-[var(--rule)] pb-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="font-serif text-[32px] font-semibold leading-tight">Cross-Company Comparison</h1>
            <p className="text-sm text-[var(--ink-2)]">
              Auditable side-by-side figures from SEC XBRL with Python Decimal recomputed financial ratios.
            </p>
          </div>
          {data && (
            <button onClick={exportCSV} className="btn text-xs font-medium hover:border-[var(--accent)]">
              📥 Export Table to CSV
            </button>
          )}
        </div>

        {/* Filters and Controls */}
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <div className="flex gap-2" role="group" aria-label="Companies">
            {companies.map((c) => {
              const on = picked.includes(c.ticker);
              return (
                <button
                  key={c.ticker}
                  aria-pressed={on}
                  onClick={() =>
                    setPicked((p) =>
                      on
                        ? p.filter((t) => t !== c.ticker)
                        : [...p, c.ticker].sort(
                            (a, b) =>
                              companies.findIndex((x) => x.ticker === a) -
                              companies.findIndex((x) => x.ticker === b)
                          )
                    )
                  }
                  className={`flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-xs font-medium transition-all ${
                    on
                      ? "border-[var(--ink)] bg-[var(--panel)] shadow-xs"
                      : "border-[var(--rule)] text-[var(--muted)] line-through opacity-60"
                  }`}
                >
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{ background: on ? seriesVar(c.ticker) : "var(--rule-strong)" }}
                    aria-hidden
                  />
                  {c.ticker}
                </button>
              );
            })}
          </div>

          <select
            className="field num text-xs"
            value={fy}
            onChange={(e) => setFy(Number(e.target.value))}
            aria-label="Year"
          >
            {years.map((y) => (
              <option key={y} value={y}>
                {align === "fiscal" ? `FY${y}` : `Calendar ${y}`}
              </option>
            ))}
          </select>

          <div
            className="inline-flex rounded-lg border border-[var(--rule-strong)] p-0.5 text-xs font-medium"
            role="radiogroup"
            aria-label="Period alignment"
          >
            {(["fiscal", "calendar"] as const).map((a) => (
              <button
                key={a}
                role="radio"
                aria-checked={align === a}
                onClick={() => setAlign(a)}
                className={`rounded-md px-3 py-1 transition-colors ${
                  align === a
                    ? "bg-[var(--accent)] text-[var(--accent-ink)] shadow-xs"
                    : "text-[var(--ink-2)] hover:bg-[var(--panel-2)]"
                }`}
              >
                {a === "fiscal" ? "Same fiscal year label" : "Closest calendar year"}
              </button>
            ))}
          </div>

          {/* Quick metric search input */}
          <div className="ml-auto">
            <input
              type="text"
              placeholder="Search metrics..."
              value={filterQuery}
              onChange={(e) => setFilterQuery(e.target.value)}
              className="field text-xs py-1 px-2.5 w-44 placeholder:text-[var(--muted)]"
            />
          </div>
        </div>
      </div>

      {error && <p className="mt-4 text-sm text-[var(--fail)]">{error}</p>}

      {data && (
        <>
          {data.period_notes.length > 0 && (
            <div className="mt-5 rounded-lg border-l-4 border-[var(--warn)] bg-[var(--warn-soft)] px-4 py-3 text-xs text-[var(--ink)]">
              <strong className="block mb-1 font-semibold">Reporting Period Notes:</strong>
              {data.period_notes.map((n, i) => (
                <p key={i} className={i ? "mt-1 text-[var(--ink-2)]" : "text-[var(--ink-2)]"}>
                  {n}
                </p>
              ))}
            </div>
          )}

          <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[1.35fr_1fr]">
            {/* Side-by-side Table */}
            <section className="panel overflow-x-auto p-2 shadow-sm">
              <table className="data">
                <thead>
                  <tr>
                    <th>Financial Metric</th>
                    {picked.map((t) => (
                      <th key={t} className="r">
                        <span className="inline-flex items-center gap-1.5">
                          <span
                            className="h-2 w-2 rounded-full"
                            style={{ background: seriesVar(t) }}
                            aria-hidden
                          />
                          <span className="font-semibold">{t}</span>{" "}
                          <span className="num font-normal text-[11px] text-[var(--muted)]">
                            FY{data.resolved_fiscal_years[t]}
                          </span>
                        </span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filteredRows.map((r) => {
                    // Compute max value for subtle relative bar
                    const numValues = picked
                      .map((t) => Number(r.values[t]?.value))
                      .filter((n) => !isNaN(n) && n > 0);
                    const maxVal = numValues.length ? Math.max(...numValues) : 1;
                    const leader = numValues.length > 1 ? picked.find((t) => Number(r.values[t]?.value) === maxVal) : undefined;

                    return (
                      <tr
                        key={r.metric}
                        id={`row-${r.metric}`}
                        className={`row-click transition-colors ${r.metric === chartMetric ? "bg-[var(--accent-soft)]" : ""}`}
                        onClick={() => {
                          setChartMetric(r.metric);
                          setFocusCell(null);
                        }}
                      >
                        <td>
                          <button
                            className="text-left font-medium text-[var(--ink)] hover:text-[var(--accent)] flex items-center gap-1.5 group"
                            onClick={(e) => {
                              e.stopPropagation();
                              setChartMetric(r.metric);
                              setFocusCell(null);
                            }}
                          >
                            <span>{r.label}</span>
                            <span className="text-[10px] opacity-0 group-hover:opacity-100 text-[var(--accent)]">
                              📊
                            </span>
                          </button>
                        </td>
                        {picked.map((t) => (
                          <Cell
                            key={t}
                            ticker={t}
                            v={r.values[t]}
                            maxVal={maxVal}
                            leader={leader === t}
                            focused={focusCell?.metric === r.metric && focusCell.ticker === t}
                            onFocus={() => {
                              setChartMetric(r.metric);
                              setFocusCell({ metric: r.metric, ticker: t });
                            }}
                          />
                        ))}
                      </tr>
                    );
                  })}
                  {filteredRows.length === 0 && (
                    <tr>
                      <td colSpan={picked.length + 1} className="text-center py-6 text-sm text-[var(--muted)]">
                        No metrics matching &ldquo;{filterQuery}&rdquo;
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </section>

            {/* Interactive Chart */}
            <section className="panel p-5 shadow-sm">
              <div className="flex items-center justify-between border-b border-[var(--rule)] pb-3">
                <label className="text-xs font-semibold text-[var(--ink)]" htmlFor="metric">
                  Visual Comparison Chart
                </label>
                <select
                  id="metric"
                  className="field text-xs font-medium"
                  value={chartMetric}
                  onChange={(e) => setChartMetric(e.target.value)}
                >
                  {data.rows.map((r) => (
                    <option key={r.metric} value={r.metric}>
                      {r.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="mt-4">
                {chartData.length ? (
                  <CompareBars
                    data={chartData}
                    unit={
                      PERCENT.has(chartMetric)
                        ? "percent"
                        : USD.has(chartMetric)
                        ? "usd"
                        : "ratio"
                    }
                    label={chartRow?.label ?? ""}
                  />
                ) : (
                  <p className="text-sm text-[var(--muted)] py-12 text-center">
                    No values available for this metric.
                  </p>
                )}
              </div>

              {focused && focusCell ? (
                <CellBreakdown v={focused} ticker={focusCell.ticker} onClose={() => setFocusCell(null)} />
              ) : (
                chartRow && (
                  <div className="mt-4 rounded-lg bg-[var(--panel-2)] p-3 text-xs text-[var(--ink-2)] border border-[var(--rule)]">
                    <span className="font-semibold block text-[var(--ink)]">Methodology:</span>
                    <span className="mt-0.5 block">
                      {Object.values(chartRow.values).find((v) => v.calculation)?.calculation?.definition ??
                        "Reported directly in SEC EDGAR XBRL filings without adjustments."}
                    </span>
                    <span className="mt-2 block text-[11px] text-[var(--muted)]">
                      Click any value in the table to see its inputs and source. <kbd>↑</kbd> <kbd>↓</kbd> step through metrics.
                    </span>
                  </div>
                )
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}

function Cell({
  v,
  ticker,
  maxVal,
  leader,
  focused,
  onFocus,
}: {
  v: MetricValue | undefined;
  ticker: string;
  maxVal: number;
  leader: boolean;
  focused: boolean;
  onFocus: () => void;
}) {
  if (!v) return <td className="r text-[var(--muted)]">—</td>;
  const numVal = Number(v.value);
  const ratio = !isNaN(numVal) && numVal > 0 && maxVal > 0 ? Math.min(100, (numVal / maxVal) * 100) : 0;

  return (
    <td className="r num relative !p-0">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onFocus();
        }}
        aria-pressed={focused}
        aria-label={`${ticker} ${v.label}: ${v.display ?? "not available"}. Show breakdown`}
        className={`group relative block w-full px-3 py-[0.55rem] text-right transition-colors hover:bg-[var(--panel-2)] ${focused ? "outline-2 -outline-offset-2 outline-[var(--accent)]" : ""}`}
      >
        {/* relative-size bar in the company's color */}
        {ratio > 0 && (
          <span
            className="pointer-events-none absolute inset-y-1 right-0 rounded-l-sm opacity-[0.13] transition-all duration-500 group-hover:opacity-25"
            style={{ width: `${ratio}%`, background: seriesVar(ticker) }}
            aria-hidden
          />
        )}
        <span className={`relative z-10 ${leader ? "font-semibold" : "font-medium"}`}>
          {leader && (
            <span className="mr-1 text-[9px] align-middle" style={{ color: seriesVar(ticker) }} title="Highest value in this row" aria-label="highest">
              ▲
            </span>
          )}
          {v.display ?? <span className="text-[var(--muted)]">n/a</span>}
          {v.warnings.length > 0 && (
            <span className="ml-1 text-[var(--warn)]" aria-label="has caveats">
              *
            </span>
          )}
        </span>
      </button>
    </td>
  );
}

/** Where one comparison value comes from: the XBRL fact, or the formula and each of its inputs. */
function CellBreakdown({ v, ticker, onClose }: { v: MetricValue; ticker: string; onClose: () => void }) {
  return (
    <div className="pop mt-4 rounded-lg border border-[var(--rule-strong)] bg-[var(--panel-2)] p-3 text-xs">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-1.5 font-semibold text-[var(--ink)]">
            <span className="h-2 w-2 rounded-full" style={{ background: seriesVar(ticker) }} aria-hidden />
            {ticker} · {v.label} · FY{v.fiscal_year}
          </div>
          <div className="num mt-0.5 text-lg font-semibold">{v.display ?? "n/a"}</div>
        </div>
        <button type="button" onClick={onClose} className="rounded px-1.5 text-[var(--muted)] hover:bg-[var(--panel)] hover:text-[var(--ink)]" aria-label="Close breakdown">
          ✕
        </button>
      </div>

      {v.error && <p className="mt-2 text-[var(--fail)]">{v.error}</p>}

      {v.calculation && (
        <>
          <code className="mt-2 block rounded bg-[var(--panel)] px-2 py-1.5 text-[var(--ink-2)]">{v.calculation.formula}</code>
          <ul className="mt-2 space-y-1">
            {v.calculation.inputs.map((i) => (
              <li key={i.name} className="flex justify-between gap-3 border-b border-dashed border-[var(--rule)] pb-1">
                <span className="text-[var(--muted)]">{i.name.replaceAll("_", " ")}</span>
                <span className="num font-medium">{i.unit === "USD" || i.unit === "USD/shares" ? factValue(i.value, i.unit) : i.value}</span>
              </li>
            ))}
          </ul>
          {v.calculation.definition && <p className="mt-2 text-[var(--ink-2)]">{v.calculation.definition}</p>}
        </>
      )}

      {v.fact && !v.calculation && (
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[var(--ink-2)]">
          <dt className="text-[var(--muted)]">XBRL tag</dt>
          <dd className="break-all">{v.fact.concept}</dd>
          <dt className="text-[var(--muted)]">Period</dt>
          <dd className="num">
            {v.fact.start ?? ""} → {v.fact.end}
          </dd>
          {v.fact.location && (
            <>
              <dt className="text-[var(--muted)]">In filing</dt>
              <dd>
                p. {v.fact.location.page} · {v.fact.location.table_title ?? "table"}
              </dd>
            </>
          )}
        </dl>
      )}

      {v.warnings.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-[var(--warn)]">
          {v.warnings.map((w, i) => (
            <li key={i}>* {w}</li>
          ))}
        </ul>
      )}

      {v.fact?.source_url && (
        <a href={v.fact.source_url} target="_blank" rel="noopener noreferrer" className="mt-2 inline-block font-medium text-[var(--accent)] hover:underline">
          Open 10-K on SEC.gov ↗
        </a>
      )}
    </div>
  );
}
