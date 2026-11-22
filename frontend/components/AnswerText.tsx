"use client";

import { Fragment, useState, useMemo, useRef, useEffect } from "react";
import type { Answer, Fact, Calculation, Passage } from "@/lib/api";
import { factValue, millions, pages, periodText, SECTION_NAMES } from "@/lib/format";

const CITE = /\[([FCS]\d+)\]/g;
const KIND_LABEL: Record<string, string> = {
  F: "Reported fact",
  C: "Calculation",
  S: "Filing passage",
};

interface AnswerTextProps {
  text: string;
  validIds?: Set<string>;
  active?: string | null;
  answer?: Answer | null;
  onCite: (id: string | null) => void;
}

/** Renders an answer with interactive provenance chips: ■F reported fact · ƒC calculation · ¶S filing passage. */
export function AnswerText({
  text,
  validIds,
  active = null,
  answer = null,
  onCite,
}: AnswerTextProps) {
  const evMap = useMemo(() => {
    const m = new Map<string, { type: "F" | "C" | "S"; data: Fact | Calculation | Passage }>();
    if (answer) {
      answer.facts?.forEach((f) => f.evidence_id && m.set(f.evidence_id, { type: "F", data: f }));
      answer.calculations?.forEach((c) => c.evidence_id && m.set(c.evidence_id, { type: "C", data: c }));
      answer.passages?.forEach((p) => p.evidence_id && m.set(p.evidence_id, { type: "S", data: p }));
    }
    return m;
  }, [answer]);

  const effectiveValidIds = useMemo(() => {
    if (validIds) return validIds;
    if (answer) {
      return new Set([...answer.facts, ...answer.calculations, ...answer.passages].map((e) => e.evidence_id ?? ""));
    }
    return new Set<string>();
  }, [validIds, answer]);

  const lines = text.split("\n");
  const blocks: { type: "p" | "li"; text: string }[] = [];
  for (const line of lines) {
    if (!line.trim()) continue;
    const m = line.match(/^\s*-\s+(.*)$/);
    blocks.push(m ? { type: "li", text: m[1] } : { type: "p", text: line });
  }

  const renderInline = (s: string) => {
    const out: React.ReactNode[] = [];
    let last = 0;
    s.replace(CITE, (match, id: string, offset: number) => {
      if (offset > last) out.push(s.slice(last, offset));
      const ok = effectiveValidIds.has(id);
      const evItem = evMap.get(id);

      out.push(
        <CitationChip
          key={`${id}-${offset}`}
          id={id}
          ok={ok}
          active={active === id}
          evidence={evItem}
          onCite={() => ok && onCite(id)}
        />
      );
      last = offset + match.length;
      return match;
    });
    if (last < s.length) out.push(s.slice(last));
    return out;
  };

  const out: React.ReactNode[] = [];
  let list: React.ReactNode[] = [];
  const flush = (k: number) => {
    if (list.length) {
      out.push(
        <ul key={`ul-${k}`} className="my-2 list-disc space-y-1.5 pl-5 marker:text-[var(--muted)]">
          {list}
        </ul>
      );
      list = [];
    }
  };
  blocks.forEach((b, i) => {
    if (b.type === "li") {
      list.push(<li key={i}>{renderInline(b.text)}</li>);
    } else {
      flush(i);
      const heading = b.text.trim().endsWith(":") && b.text.length < 120;
      out.push(
        <p key={i} className={heading ? "mt-3 font-sans text-sm font-semibold text-[var(--ink-2)]" : "my-2"}>
          {renderInline(b.text)}
        </p>
      );
    }
  });
  flush(blocks.length);
  return <div className="prose-answer">{out.map((n, i) => <Fragment key={i}>{n}</Fragment>)}</div>;
}

function CitationChip({
  id,
  ok,
  active,
  evidence,
  onCite,
}: {
  id: string;
  ok: boolean;
  active: boolean;
  evidence?: { type: "F" | "C" | "S"; data: Fact | Calculation | Passage };
  onCite: () => void;
}) {
  const [showHover, setShowHover] = useState(false);
  const hoverTimeout = useRef<NodeJS.Timeout | null>(null);

  const handleMouseEnter = () => {
    if (hoverTimeout.current) clearTimeout(hoverTimeout.current);
    setShowHover(true);
  };

  const handleMouseLeave = () => {
    hoverTimeout.current = setTimeout(() => setShowHover(false), 200);
  };

  useEffect(() => {
    return () => {
      if (hoverTimeout.current) clearTimeout(hoverTimeout.current);
    };
  }, []);

  return (
    <span
      className="relative inline-block align-baseline"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onFocus={handleMouseEnter}
      onBlur={handleMouseLeave}
      onKeyDown={(e) => e.key === "Escape" && setShowHover(false)}
    >
      <button
        type="button"
        className={`cite ${ok ? `cite-${id[0]}` : "cite-bad"} cursor-pointer transition-transform hover:scale-110`}
        data-active={active}
        data-cite={id}
        aria-label={ok ? `${KIND_LABEL[id[0]]} ${id}` : `Invalid citation ${id}`}
        title={ok ? undefined : "This citation does not match any evidence the system retrieved"}
        onClick={onCite}
      >
        {id}
      </button>

      {/* Floating Hovercard Preview */}
      {showHover && ok && evidence && (
        <div
          className="absolute bottom-full left-1/2 z-50 mb-2 w-72 -translate-x-1/2 rounded-xl border border-[var(--rule-strong)] bg-[var(--panel)] p-3 text-left font-sans text-xs shadow-2xl transition-all"
          style={{ animation: "fadeIn 150ms ease-out" }}
        >
          {evidence.type === "F" && <FactHover fact={evidence.data as Fact} id={id} />}
          {evidence.type === "C" && <CalcHover calc={evidence.data as Calculation} id={id} />}
          {evidence.type === "S" && <PassageHover passage={evidence.data as Passage} id={id} />}
          <div className="mt-2 border-t border-[var(--rule)] pt-1.5 text-[10px] text-[var(--muted)]">Click the chip to open full proof in the evidence panel</div>

          {/* Little arrow at the bottom */}
          <div className="absolute -bottom-1.5 left-1/2 h-3 w-3 -translate-x-1/2 rotate-45 border-b border-r border-[var(--rule-strong)] bg-[var(--panel)]" />
        </div>
      )}
    </span>
  );
}

function FactHover({ fact, id }: { fact: Fact; id: string }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between border-b border-[var(--rule)] pb-1.5">
        <span className="font-semibold text-[var(--ink)]">
          {fact.ticker} · {fact.label}
        </span>
        <span className="cite cite-F !m-0">{id}</span>
      </div>
      <div className="num text-base font-bold text-[var(--accent)]">
        {factValue(fact.value, fact.unit)}
      </div>
      <div className="text-[11px] text-[var(--ink-2)]">
        <div>
          <span className="text-[var(--muted)]">Period: </span>
          FY{fact.fiscal_year} ({periodText(fact.start, fact.end)})
        </div>
        {fact.location && (
          <div>
            <span className="text-[var(--muted)]">Location: </span>
            p. {fact.location.page} · {fact.location.table_title ?? "table"}
            {fact.location.row_label ? ` · “${fact.location.row_label}”` : ""}
          </div>
        )}
      </div>
      {fact.source_url && (
        <a
          href={fact.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-block pt-1 font-medium text-[var(--accent)] hover:underline"
        >
          Open 10-K on SEC.gov ↗
        </a>
      )}
    </div>
  );
}

function CalcHover({ calc, id }: { calc: Calculation; id: string }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between border-b border-[var(--rule)] pb-1.5">
        <span className="font-semibold text-[var(--ink)]">
          {calc.ticker} · {calc.label}
        </span>
        <span className="cite cite-C !m-0">{id}</span>
      </div>
      <div className="num text-base font-bold text-[var(--accent)]">{calc.display}</div>
      <code className="block rounded bg-[var(--panel-2)] px-2 py-1 font-mono text-[10px] text-[var(--ink-2)]">
        {calc.formula}
      </code>
      <div className="space-y-0.5 text-[11px] text-[var(--ink-2)]">
        {calc.inputs.map((inp) => (
          <div key={inp.name} className="flex justify-between">
            <span className="text-[var(--muted)]">{inp.name}:</span>
            <span className="num font-medium">{inp.unit === "USD" ? millions(inp.value) : inp.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function PassageHover({ passage, id }: { passage: Passage; id: string }) {
  const ch = passage.chunk;
  const pg = pages(ch.page_start, ch.page_end);
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between border-b border-[var(--rule)] pb-1.5">
        <span className="font-semibold text-[var(--ink)]">
          {ch.ticker} FY{ch.fiscal_year} 10-K
        </span>
        <span className="cite cite-S !m-0">{id}</span>
      </div>
      <div className="text-[11px] font-medium text-[var(--ink-2)]">
        {SECTION_NAMES[ch.section] ?? ch.section_title} {pg ? `(${pg})` : ""}
      </div>
      <p className="line-clamp-3 text-[11px] italic leading-relaxed text-[var(--ink-2)]">
        &ldquo;{ch.text.slice(0, 160)}&hellip;&rdquo;
      </p>
      {ch.source_url && (
        <a
          href={ch.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-block pt-1 font-medium text-[var(--accent)] hover:underline"
        >
          View section in 10-K ↗
        </a>
      )}
    </div>
  );
}
