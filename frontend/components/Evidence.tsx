"use client";

import { useEffect, useRef, useState } from "react";
import type { Answer, Calculation, Fact, Passage } from "@/lib/api";
import { SECTION_NAMES, factValue, millions, pages, periodText } from "@/lib/format";

function SourceLink({ href, children }: { href: string | null; children: React.ReactNode }) {
  if (!href) return null;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className="text-[13px] font-medium text-[var(--accent)] underline-offset-2 hover:underline">
      {children}
    </a>
  );
}

function Card({ id, active, onSelect, children }: { id: string; active: boolean; onSelect?: (id: string) => void; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (active) ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [active]);
  return (
    <div
      ref={ref}
      id={`ev-${id}`}
      className={`inset p-3 transition-all ${active ? "evidence-active" : ""} ${onSelect ? "cursor-pointer hover:border-[var(--rule-strong)] hover:shadow-sm" : ""}`}
      onClick={(e) => {
        // links and buttons inside the card keep their own behaviour
        if (!onSelect || (e.target as HTMLElement).closest("a,button")) return;
        onSelect(id);
      }}
      title={onSelect ? "Highlight where this is cited in the answer" : undefined}
    >
      {children}
    </div>
  );
}

function Tag({ id }: { id: string }) {
  return <span className={`cite cite-${id[0]} !m-0 !align-baseline`}>{id}</span>;
}

export function FactCard({ f, active, onSelect }: { f: Fact; active: boolean; onSelect?: (id: string) => void }) {
  const id = f.evidence_id ?? "";
  return (
    <Card id={id} active={active} onSelect={onSelect}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <Tag id={id} />
          <span className="text-sm font-medium">
            {f.ticker} · {f.label}
          </span>
        </div>
        <span className="num text-sm font-semibold">{factValue(f.value, f.unit)}</span>
      </div>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs text-[var(--ink-2)]">
        <dt className="text-[var(--muted)]">Reported</dt>
        <dd className="num">{f.unit === "USD" ? millions(f.value) : f.value}</dd>
        <dt className="text-[var(--muted)]">Period</dt>
        <dd className="num">FY{f.fiscal_year} · {periodText(f.start, f.end)}</dd>
        <dt className="text-[var(--muted)]">XBRL tag</dt>
        <dd className="break-all">{f.concept}</dd>
        {f.location && (
          <>
            <dt className="text-[var(--muted)]">In filing</dt>
            <dd>
              p. {f.location.page} · {f.location.table_title ?? "table"}
              {f.location.row_label ? ` · row “${f.location.row_label}”` : ""}
            </dd>
          </>
        )}
        <dt className="text-[var(--muted)]">Filing</dt>
        <dd className="num">
          10-K {f.accession} · filed {f.filed}
        </dd>
      </dl>
      <div className="mt-2">
        <SourceLink href={f.source_url}>Open 10-K on SEC.gov</SourceLink>
      </div>
    </Card>
  );
}

export function CalcCard({ c, active, onCite }: { c: Calculation; active: boolean; onCite: (id: string) => void }) {
  const id = c.evidence_id ?? "";
  return (
    <Card id={id} active={active} onSelect={onCite}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <Tag id={id} />
          <span className="text-sm font-medium">
            {c.ticker} · {c.label}
          </span>
        </div>
        <span className="num text-sm font-semibold">{c.display}</span>
      </div>
      <code className="mt-2 block rounded bg-[var(--panel)] px-2 py-1.5 text-xs text-[var(--ink-2)]">{c.formula}</code>
      <table className="mt-2 w-full text-xs">
        <tbody>
          {c.inputs.map((i) => (
            <tr key={i.name} className="border-t border-[var(--rule)] first:border-t-0">
              <td className="py-1 pr-2 text-[var(--muted)]">{i.name}</td>
              <td className="num py-1 pr-2 text-right">{i.unit === "USD" || i.unit === "USD/shares" ? factValue(i.value, i.unit) : i.value}</td>
              <td className="py-1 text-right">
                {i.evidence_id ? (
                  <button type="button" className="cite cite-F !align-baseline" onClick={() => onCite(i.evidence_id!)}>
                    {i.evidence_id}
                  </button>
                ) : (
                  <span className="text-[var(--muted)]">FY{i.fiscal_year}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="num mt-1 text-[11px] text-[var(--muted)]">Exact result {c.result}</div>
      {c.definition && <p className="mt-1.5 text-xs text-[var(--ink-2)]">{c.definition}</p>}
      {c.warnings.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 text-xs text-[var(--warn)]">
          {c.warnings.map((w, k) => (
            <li key={k}>{w}</li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function PassageCard({ p, active, onSelect }: { p: Passage; active: boolean; onSelect?: (id: string) => void }) {
  const id = p.evidence_id ?? "";
  const ch = p.chunk;
  const pg = pages(ch.page_start, ch.page_end);
  const [expanded, setExpanded] = useState(false);
  const long = ch.text.length > 420;
  const open = expanded || active;
  return (
    <Card id={id} active={active} onSelect={onSelect}>
      <div className="flex items-center gap-2">
        <Tag id={id} />
        <span className="text-sm font-medium">
          {ch.ticker} FY{ch.fiscal_year} 10-K · {SECTION_NAMES[ch.section] ?? ch.section_title}
        </span>
      </div>
      {ch.subsection && <div className="mt-1 line-clamp-2 text-xs italic text-[var(--ink-2)]">{ch.subsection}</div>}
      <p className={`mt-2 whitespace-pre-line text-[13px] leading-relaxed ${open ? "" : "line-clamp-5"}`}>{ch.text}</p>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--muted)]">
        {long && (
          <button type="button" className="font-medium text-[var(--ink-2)] hover:text-[var(--accent)]" onClick={() => setExpanded((x) => !x)} aria-expanded={open}>
            {open ? "Show less" : "Show full passage"}
          </button>
        )}
        {pg && <span>{pg}</span>}
        {p.scores.rerank_score !== null && <span className="num">relevance {p.scores.rerank_score.toFixed(2)}</span>}
        {ch.injection_flags.length > 0 && <span className="text-[var(--warn)]">flagged: {ch.injection_flags.join(", ")}</span>}
        <SourceLink href={ch.source_url}>View source</SourceLink>
      </div>
    </Card>
  );
}

type Filter = "all" | "C" | "F" | "S";

export function EvidencePanel({ answer, active, onCite }: { answer: Answer; active: string | null; onCite: (id: string) => void }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");

  // a newly selected answer starts unfiltered
  useEffect(() => {
    setFilter("all");
    setQuery("");
  }, [answer.run_id]);
  // jumping to a cited item must never be hidden by a filter
  useEffect(() => {
    if (active) {
      setFilter((f) => (f === "all" || f === active[0] ? f : "all"));
      setQuery("");
    }
  }, [active]);

  const q = query.trim().toLowerCase();
  const has = (s: string) => !q || s.toLowerCase().includes(q);
  const calcs = answer.calculations.filter((c) => has(`${c.evidence_id} ${c.ticker} ${c.label} ${c.formula}`));
  const facts = answer.facts.filter((f) => has(`${f.evidence_id} ${f.ticker} ${f.label} ${f.concept}`));
  const passages = answer.passages.filter((p) => has(`${p.evidence_id} ${p.chunk.ticker} ${p.chunk.section_title} ${p.chunk.subsection ?? ""} ${p.chunk.text}`));
  const total = answer.facts.length + answer.calculations.length + answer.passages.length;
  const shown = (f: Filter) => filter === "all" || filter === f;

  if (total === 0) return <p className="text-sm text-[var(--muted)]">No evidence was used for this answer.</p>;

  const tabs: { id: Filter; label: string; n: number }[] = [
    { id: "all", label: "All", n: total },
    { id: "C", label: "Calculations", n: answer.calculations.length },
    { id: "F", label: "Facts", n: answer.facts.length },
    { id: "S", label: "Passages", n: answer.passages.length },
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Evidence type">
          {tabs
            .filter((t) => t.id === "all" || t.n > 0)
            .map((t) => (
              <button key={t.id} role="tab" aria-selected={filter === t.id} onClick={() => setFilter(t.id)} className="chip !px-2.5 !py-1 !text-[11px]">
                {t.label} <span className="num opacity-70">{t.n}</span>
              </button>
            ))}
        </div>
        {total > 4 && (
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter evidence by company, tag or text…"
            className="field !py-1 text-xs placeholder:text-[var(--muted)]"
            aria-label="Filter evidence"
          />
        )}
      </div>

      {shown("C") && calcs.length > 0 && (
        <section className="stagger flex flex-col gap-2">
          <GroupHead title="Calculations" hint="Python Decimal, recomputed during verification" n={calcs.length} />
          {calcs.map((c) => (
            <CalcCard key={c.id} c={c} active={active === c.evidence_id} onCite={onCite} />
          ))}
        </section>
      )}
      {shown("F") && facts.length > 0 && (
        <section className="stagger flex flex-col gap-2">
          <GroupHead title="Reported facts" hint="SEC XBRL — the number of record" n={facts.length} />
          {facts.map((f) => (
            <FactCard key={f.id} f={f} active={active === f.evidence_id} onSelect={onCite} />
          ))}
        </section>
      )}
      {shown("S") && passages.length > 0 && (
        <section className="stagger flex flex-col gap-2">
          <GroupHead title="Filing passages" hint="Hybrid search, reranked" n={passages.length} />
          {passages.map((p) => (
            <PassageCard key={p.chunk.id} p={p} active={active === p.evidence_id} onSelect={onCite} />
          ))}
        </section>
      )}
      {q && calcs.length + facts.length + passages.length === 0 && <p className="text-sm text-[var(--muted)]">No evidence matches &ldquo;{query}&rdquo;.</p>}
    </div>
  );
}

function GroupHead({ title, hint, n }: { title: string; hint: string; n: number }) {
  return (
    <div className="flex items-baseline justify-between">
      <h3 className="text-sm font-semibold">
        {title} <span className="num font-normal text-[var(--muted)]">{n}</span>
      </h3>
      <span className="text-xs text-[var(--muted)]">{hint}</span>
    </div>
  );
}
