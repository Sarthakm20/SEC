"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useKeydown } from "@/lib/hooks";

type Item = { id: string; group: string; label: string; hint?: string; run: () => void };

const PAGES = [
  { href: "/", label: "Overview", hint: "Company KPIs, trends and ratios" },
  { href: "/research", label: "Research Assistant", hint: "Ask a cited question" },
  { href: "/compare", label: "Compare", hint: "Side-by-side company figures" },
  { href: "/inspector", label: "Inspector", hint: "Trace and verification of past runs" },
  { href: "/benchmark", label: "Benchmark & Ablation", hint: "Pipeline A–E evaluation" },
];

const STARTERS = [
  "What was Apple's gross margin in FY2024?",
  "Compare Microsoft's and Apple's net margins in FY2024",
  "What was NVIDIA's revenue growth in FY2025?",
  "What are Apple's primary supply chain risk factors?",
];

export function openPalette() {
  window.dispatchEvent(new Event("open-palette"));
}

/** Ctrl/⌘+K: jump to a page or ask the research assistant, all from the keyboard. */
export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  useKeydown((e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      setOpen((o) => !o);
    }
  });

  useEffect(() => {
    const fn = () => setOpen(true);
    window.addEventListener("open-palette", fn);
    return () => window.removeEventListener("open-palette", fn);
  }, []);

  useEffect(() => {
    if (open) {
      setQ("");
      setIdx(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const close = () => setOpen(false);

  const items = useMemo<Item[]>(() => {
    const term = q.trim().toLowerCase();
    const ask = (question: string) => () => {
      close();
      router.push(`/research?q=${encodeURIComponent(question)}`);
    };
    const pages: Item[] = PAGES.map((p) => ({
      id: `page-${p.href}`,
      group: "Go to",
      label: p.label,
      hint: p.hint,
      run: () => {
        close();
        router.push(p.href);
      },
    }));
    const starters: Item[] = STARTERS.map((s) => ({ id: `ask-${s}`, group: "Ask", label: s, run: ask(s) }));
    const match = (i: Item) => !term || i.label.toLowerCase().includes(term) || i.hint?.toLowerCase().includes(term);
    const filtered = [...pages, ...starters].filter(match);
    if (term.length >= 3) {
      filtered.unshift({ id: "ask-free", group: "Ask", label: `Ask: “${q.trim()}”`, hint: "Send to the research assistant", run: ask(q.trim()) });
    }
    return filtered;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, router]);

  useEffect(() => setIdx(0), [q]);
  useEffect(() => {
    listRef.current?.querySelector(`[data-idx="${idx}"]`)?.scrollIntoView({ block: "nearest" });
  }, [idx]);

  if (!open) return null;

  let lastGroup = "";
  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center bg-black/35 px-4 pt-[12vh]" onPointerDown={close} role="presentation">
      <div
        className="popover pop w-full max-w-xl overflow-hidden"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onPointerDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-[var(--rule)] px-4">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--muted)" strokeWidth="2" strokeLinecap="round" aria-hidden>
            <path d="M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM16 16l5 5" />
          </svg>
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setIdx((i) => Math.min(i + 1, items.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setIdx((i) => Math.max(i - 1, 0));
              } else if (e.key === "Enter") {
                e.preventDefault();
                items[idx]?.run();
              } else if (e.key === "Escape") {
                close();
              }
            }}
            placeholder="Type a page, an action, or a question to ask…"
            className="h-12 flex-1 bg-transparent text-[15px] outline-none placeholder:text-[var(--muted)]"
            aria-label="Search commands"
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-list"
            aria-activedescendant={items[idx] ? `pal-${idx}` : undefined}
          />
          <kbd>Esc</kbd>
        </div>
        <ul id="palette-list" ref={listRef} role="listbox" className="max-h-[50vh] overflow-y-auto p-2">
          {items.length === 0 && <li className="px-3 py-6 text-center text-sm text-[var(--muted)]">Nothing matches. Type 3+ characters to ask it as a question.</li>}
          {items.map((it, i) => {
            const head = it.group !== lastGroup ? it.group : null;
            lastGroup = it.group;
            return (
              <li key={it.id} role="presentation">
                {head && <div className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-[var(--muted)]">{head}</div>}
                <div
                  id={`pal-${i}`}
                  data-idx={i}
                  role="option"
                  aria-selected={i === idx}
                  onPointerMove={() => setIdx(i)}
                  onClick={it.run}
                  className={`flex cursor-pointer items-center justify-between gap-3 rounded-lg px-3 py-2 text-sm ${i === idx ? "bg-[var(--accent-soft)] text-[var(--accent)]" : "text-[var(--ink)]"}`}
                >
                  <span className="truncate">{it.label}</span>
                  {it.hint && <span className="shrink-0 text-xs text-[var(--muted)]">{it.hint}</span>}
                </div>
              </li>
            );
          })}
        </ul>
        <div className="flex items-center gap-3 border-t border-[var(--rule)] px-4 py-2 text-[11px] text-[var(--muted)]">
          <span className="flex items-center gap-1">
            <kbd>↑</kbd>
            <kbd>↓</kbd> move
          </span>
          <span className="flex items-center gap-1">
            <kbd>↵</kbd> select
          </span>
          <span className="ml-auto flex items-center gap-1">
            <kbd>Ctrl</kbd>
            <kbd>K</kbd> toggle
          </span>
        </div>
      </div>
    </div>
  );
}
