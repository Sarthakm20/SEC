"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { TrendChart } from "@/components/Charts";
import { api, type Company, type MetricValue, type Overview } from "@/lib/api";
import { SECTION_NAMES, factValue, pct, seriesVar } from "@/lib/format";

const TRENDS = [
  { key: "revenue", name: "Revenue" },
  { key: "net_income", name: "Net income" },
  { key: "free_cash_flow", name: "Free cash flow" },
] as const;

const askHref = (q: string) => `/research?q=${encodeURIComponent(q)}`;

export default function OverviewPage() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [ticker, setTicker] = useState<string | null>(null);
  const [fy, setFy] = useState<number | null>(null);
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loadedKey = useRef<string | null>(null);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    api
      .companies()
      .then((cs) => {
        setCompanies(cs);
        if (cs.length) setTicker(cs[0].ticker);
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!ticker) return;
    // Setting fy from a response would otherwise refetch the same overview.
    if (loadedKey.current === `${ticker}:${fy}`) return;
    let cancelled = false;
    setLoading(true);
    api
      .overview(ticker, fy ?? undefined)
      .then((d) => {
        if (cancelled) return;
        loadedKey.current = `${ticker}:${d.fiscal_year}`;
        setData(d);
        setFy(d.fiscal_year);
      })
      .catch((e) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [ticker, fy]);

  const company = companies.find((c) => c.ticker === ticker);
  // only years whose 10-K text is ingested, so every year shows its indexed sections
  const years = company ? [...company.years.filings].sort((a, b) => b - a) : [];

  const pickCompany = (t: string) => {
    if (t === ticker) return;
    setFy(null);
    setTicker(t);
  };

  if (error) return <EmptyState message={error} />;
  if (!companies.length) return <OverviewSkeleton />;

  // a fresh company with nothing loaded yet shows the skeleton; a year switch keeps the old view, dimmed
  const showSkeleton = !data || data.company.ticker !== ticker;

  return (
    <div className="mx-auto max-w-6xl">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap items-center gap-2" role="tablist" aria-label="Company">
          {companies.map((c, i) => (
            <button
              key={c.ticker}
              ref={(el) => {
                tabRefs.current[i] = el;
              }}
              role="tab"
              aria-selected={c.ticker === ticker}
              tabIndex={c.ticker === ticker ? 0 : -1}
              onClick={() => pickCompany(c.ticker)}
              onKeyDown={(e) => {
                if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
                e.preventDefault();
                const n = (i + (e.key === "ArrowRight" ? 1 : -1) + companies.length) % companies.length;
                pickCompany(companies[n].ticker);
                tabRefs.current[n]?.focus();
              }}
              title={c.name}
              className={`flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-sm transition-all ${
                c.ticker === ticker ? "border-[var(--ink)] bg-[var(--panel)] font-medium shadow-xs" : "border-[var(--rule)] text-[var(--ink-2)] hover:-translate-y-px hover:border-[var(--rule-strong)]"
              }`}
            >
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: seriesVar(c.ticker) }} aria-hidden />
              {c.ticker}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2 text-sm text-[var(--ink-2)]">
          <span className="hidden sm:inline">Fiscal year</span>
          <div className="inline-flex rounded-lg border border-[var(--rule-strong)] p-0.5" role="radiogroup" aria-label="Fiscal year">
            {years
              .slice()
              .sort((a, b) => a - b)
              .map((y) => (
                <button
                  key={y}
                  role="radio"
                  aria-checked={fy === y}
                  onClick={() => setFy(y)}
                  title={`FY${y} 10-K`}
                  className={`num rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    fy === y ? "bg-[var(--accent)] text-[var(--accent-ink)] shadow-xs" : "text-[var(--ink-2)] hover:bg-[var(--panel-2)]"
                  }`}
                >
                  FY{String(y).slice(-2)}
                </button>
              ))}
          </div>
        </div>
      </div>

      {showSkeleton ? (
        <OverviewSkeleton bare />
      ) : (
        <div className={`transition-opacity duration-200 ${loading ? "opacity-50" : ""}`} aria-busy={loading}>
          <header className="rise mt-8" key={`${data.company.ticker}-h`}>
            <h1 className="font-serif text-[40px] font-semibold leading-[1.1] tracking-tight">{data.company.name}</h1>
            <p className="mt-2 text-[15px] text-[var(--ink-2)]">
              Fiscal {data.fiscal_year}
              {data.kpis[0]?.period_end ? `, ended ${new Date(data.kpis[0].period_end + "T00:00:00").toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}` : ""}.{" "}
              {data.filing ? (
                <>
                  Annual report filed {data.filing.filing_date}.{" "}
                  <a className="font-medium text-[var(--accent)] hover:underline" href={data.filing.url} target="_blank" rel="noopener noreferrer">
                    Open the 10-K ↗
                  </a>
                </>
              ) : (
                "Narrative sections for this year are not ingested; figures come from SEC XBRL."
              )}
            </p>
          </header>

          <section
            key={`${data.company.ticker}-${data.fiscal_year}-k`}
            className="stagger mt-6 grid grid-cols-1 gap-px overflow-hidden rounded-xl border border-[var(--rule)] bg-[var(--rule)] sm:grid-cols-2 lg:grid-cols-4"
            aria-label="Key figures"
          >
            {data.kpis.map((k) => (
              <Kpi key={k.metric} k={k} company={data.company.name} />
            ))}
          </section>

          <section className="mt-8 grid grid-cols-1 gap-4 lg:grid-cols-3" aria-label="Multi-year trends">
            {TRENDS.map((s) => (
              <div key={s.key} className="panel p-4 transition-shadow hover:shadow-md">
                <div className="flex items-baseline justify-between gap-2">
                  <h2 className="text-sm font-semibold">{s.name}</h2>
                  <span className="text-[11px] text-[var(--muted)]">click a year</span>
                </div>
                <p className="text-xs text-[var(--muted)]">USD billions, by fiscal year</p>
                <TrendChart
                  data={data.trend.map((t) => ({ label: `FY${t.fiscal_year}`, [s.key]: t[s.key] }))}
                  series={[{ key: s.key, name: s.name, color: seriesVar(data.company.ticker) }]}
                  activeLabel={`FY${data.fiscal_year}`}
                  onSelect={(label) => {
                    const y = Number(label.replace("FY", ""));
                    if (company?.years.filings.includes(y)) setFy(y);
                  }}
                />
              </div>
            ))}
          </section>

          <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]">
            <section className="panel p-5">
              <h2 className="font-serif text-xl font-semibold">Ratios</h2>
              <p className="text-[15px] text-[var(--muted)]">Computed with Python Decimal from reported XBRL facts. Click a row to see the inputs.</p>
              <table className="data mt-3 !text-base">
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th className="r">FY{data.fiscal_year}</th>
                    <th>How it is calculated</th>
                    <th aria-label="Expand" />
                  </tr>
                </thead>
                <tbody>
                  {data.ratios.map((r) => (
                    <RatioRow key={r.metric} r={r} company={data.company.name} fy={data.fiscal_year} />
                  ))}
                </tbody>
              </table>
            </section>

            <section className="panel p-5">
              <h2 className="font-serif text-xl font-semibold">What was indexed</h2>
              {data.filing ? (
                <>
                  <p className="text-sm text-[var(--muted)]">
                    {data.filing.n_chunks} passages from the FY{data.fiscal_year} 10-K; {data.filing.n_facts_located} XBRL facts traced to their table cell.
                  </p>
                  <SectionBars sections={data.filing.sections} company={data.company.name} fy={data.fiscal_year} />
                  <a className="mt-3 inline-block text-sm font-medium text-[var(--accent)] hover:underline" href={data.filing.index_url} target="_blank" rel="noopener noreferrer">
                    Filing index on EDGAR ↗
                  </a>
                </>
              ) : (
                <p className="mt-2 text-sm text-[var(--muted)]">No 10-K text is indexed for FY{data.fiscal_year}.</p>
              )}
            </section>
          </div>
        </div>
      )}
    </div>
  );
}

function Kpi({ k, company }: { k: Overview["kpis"][number]; company: string }) {
  const yoy = k.yoy !== null ? Number(k.yoy) : null;
  const loc = k.fact?.location;
  return (
    <div className="group relative bg-[var(--panel)] p-5 transition-colors hover:bg-[var(--panel-2)]">
      <div className="flex items-start justify-between gap-2">
        <div className="text-sm text-[var(--ink-2)]">{k.label}</div>
        <Link
          href={askHref(`What was ${company}'s ${k.label.toLowerCase()} in FY${k.fiscal_year}, and how did it change from the prior year?`)}
          className="rounded-md px-1.5 py-0.5 text-[11px] font-medium text-[var(--accent)] opacity-0 transition-opacity hover:bg-[var(--accent-soft)] focus-visible:opacity-100 group-hover:opacity-100"
          title="Ask the research assistant about this figure"
        >
          Ask →
        </Link>
      </div>
      <div className="num mt-1 text-[30px] font-semibold leading-tight tracking-tight">{k.display ?? "—"}</div>
      {yoy !== null && (
        <div className="num mt-1 flex items-center gap-1 text-sm" style={{ color: yoy >= 0 ? "var(--ok)" : "var(--fail)" }}>
          <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden>
            <path d={yoy >= 0 ? "M5 1l4 7H1z" : "M5 9L1 2h8z"} fill="currentColor" />
          </svg>
          {pct(yoy)} <span className="text-[var(--muted)]">vs prior year</span>
        </div>
      )}
      <div className="mt-3 text-xs text-[var(--muted)]">
        {k.kind === "reported" && loc ? (
          <a href={k.fact?.source_url ?? "#"} target="_blank" rel="noopener noreferrer" className="hover:text-[var(--accent)] hover:underline">
            p. {loc.page} · {loc.table_title?.toLowerCase().replace(/^\w/, (c) => c.toUpperCase())}
          </a>
        ) : k.calculation ? (
          <span>Calculated: {k.calculation.formula.replaceAll("_", " ")}</span>
        ) : (
          <span>{k.error}</span>
        )}
      </div>
    </div>
  );
}

function RatioRow({ r, company, fy }: { r: MetricValue; company: string; fy: number }) {
  const [open, setOpen] = useState(false);
  const calc = r.calculation;
  const expandable = !!calc;
  return (
    <>
      <tr
        className={expandable ? "row-click" : undefined}
        onClick={() => expandable && setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (expandable && (e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            setOpen((o) => !o);
          }
        }}
        tabIndex={expandable ? 0 : undefined}
        aria-expanded={expandable ? open : undefined}
      >
        <td className="whitespace-nowrap font-medium">{r.label}</td>
        <td className="r num font-semibold">{r.display ?? "—"}</td>
        <td className="text-[15px] leading-snug text-[var(--ink-2)]">{r.error ?? calc?.definition}</td>
        <td className="w-6 text-[var(--muted)]">
          {expandable && (
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" className={`transition-transform ${open ? "rotate-180" : ""}`} aria-hidden>
              <path d="M6 9l6 6 6-6" />
            </svg>
          )}
        </td>
      </tr>
      {open && calc && (
        <tr>
          <td colSpan={4} className="!border-b !pt-0">
            <div className="rise inset mt-1 p-3 text-sm">
              <code className="block text-[var(--ink-2)]">
                {calc.formula} = <strong className="text-[var(--ink)]">{calc.display}</strong>
              </code>
              <ul className="mt-2 grid grid-cols-1 gap-1 sm:grid-cols-2">
                {calc.inputs.map((i) => (
                  <li key={i.name} className="flex justify-between gap-3 border-b border-dashed border-[var(--rule)] pb-1">
                    <span className="text-[var(--muted)]">{i.name.replaceAll("_", " ")}</span>
                    <span className="num font-medium">{i.unit === "USD" || i.unit === "USD/shares" ? factValue(i.value, i.unit) : i.value}</span>
                  </li>
                ))}
              </ul>
              {calc.warnings.length > 0 && <p className="mt-2 text-[var(--warn)]">{calc.warnings.join(" ")}</p>}
              <Link href={askHref(`What was ${company}'s ${r.label.toLowerCase()} in FY${fy}?`)} className="mt-2 inline-block font-medium text-[var(--accent)] hover:underline">
                Ask with citations →
              </Link>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

/** Indexed sections as proportional bars; each one is a shortcut to a question about that section. */
function SectionBars({ sections, company, fy }: { sections: NonNullable<Overview["filing"]>["sections"]; company: string; fy: number }) {
  const entries = Object.entries(sections);
  const max = Math.max(1, ...entries.map(([, s]) => s.chunks));
  return (
    <ul className="stagger mt-3 space-y-1 text-sm">
      {entries.map(([k, s]) => {
        const name = SECTION_NAMES[k] ?? s.title;
        return (
          <li key={k}>
            <Link
              href={askHref(`Summarize the key points of ${company}'s FY${fy} 10-K ${name.replace(" · ", ": ")}`)}
              className="group block rounded-md px-2 py-1.5 transition-colors hover:bg-[var(--panel-2)]"
              title="Ask the research assistant about this section"
            >
              <div className="flex items-baseline justify-between gap-3">
                <span className="group-hover:text-[var(--accent)]">{name}</span>
                <span className="num text-xs text-[var(--muted)]">
                  pp. {s.page_start}–{s.page_end} · {s.chunks}
                </span>
              </div>
              <div className="mt-1 h-1 overflow-hidden rounded-full bg-[var(--panel-2)]">
                <div className="h-full rounded-full bg-[var(--rule-strong)] transition-all duration-500 group-hover:bg-[var(--accent)]" style={{ width: `${(s.chunks / max) * 100}%` }} />
              </div>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function OverviewSkeleton({ bare = false }: { bare?: boolean }) {
  return (
    <div className={bare ? "" : "mx-auto max-w-6xl"} aria-busy="true" aria-label="Loading">
      {!bare && (
        <div className="flex gap-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="skeleton h-8 w-20 !rounded-full" />
          ))}
        </div>
      )}
      <div className="skeleton mt-8 h-10 w-96 max-w-full" />
      <div className="skeleton mt-3 h-4 w-[32rem] max-w-full" />
      <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="skeleton h-32" />
        ))}
      </div>
      <div className="mt-8 grid grid-cols-1 gap-4 lg:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="skeleton h-72" />
        ))}
      </div>
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="mx-auto mt-16 max-w-lg panel p-6">
      <h1 className="font-serif text-2xl font-semibold">The backend isn’t answering</h1>
      <p className="mt-2 text-sm text-[var(--ink-2)]">{message}</p>
      <p className="mt-3 text-sm text-[var(--ink-2)]">
        Start it from <code>backend/</code> with <code>uvicorn app.api.main:app --port 8000</code>, and ingest filings first with <code>python -m app.cli ingest</code>.
      </p>
      <button className="btn mt-4" onClick={() => window.location.reload()}>
        Retry
      </button>
    </div>
  );
}
