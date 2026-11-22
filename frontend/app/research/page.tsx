"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { AnswerText } from "@/components/AnswerText";
import { EvidencePanel } from "@/components/Evidence";
import { Trace } from "@/components/Trace";
import { VerdictBadge } from "@/components/Verdict";
import { api, ApiError, type Answer } from "@/lib/api";
import { ms } from "@/lib/format";
import { isTyping, useKeydown } from "@/lib/hooks";

type Turn = { id: string; question: string; answer?: Answer; error?: string };

const EXPERIMENTS = [
  { id: "E", label: "Pipeline E · Agentic loop + XBRL + verification" },
  { id: "D", label: "Pipeline D · XBRL + Decimal + verification, single pass" },
  { id: "C", label: "Pipeline C · Reranked Hybrid RAG only" },
  { id: "B", label: "Pipeline B · Hybrid RAG (BM25 + Dense)" },
  { id: "A", label: "Pipeline A · Dense RAG baseline" },
];

const CURATED_CATEGORIES = [
  {
    name: "Key Ratios & Margins",
    queries: [
      "What was Apple's gross margin in FY2024?",
      "What was NVIDIA's operating margin in FY2025?",
      "Compare Microsoft's and Apple's net margins in FY2024",
    ],
  },
  {
    name: "Growth & Multi-Year Trends",
    queries: [
      "How did Apple's revenue change from FY2023 to FY2025?",
      "What was NVIDIA's revenue growth in FY2025?",
      "What was Microsoft's free cash flow in FY2025?",
    ],
  },
  {
    name: "10-K Narrative & Risks",
    queries: [
      "What are Apple's primary supply chain risk factors?",
      "How does Microsoft describe its AI business risks in Item 1A?",
      "What are NVIDIA's main customer concentration disclosures?",
    ],
  },
  {
    name: "Verification & Integrity",
    queries: [
      "What is Tesla's revenue in FY2024? (Tests abstention)",
      "What was Apple's research and development intensity in FY2024?",
      "How does Apple recognize revenue from services?",
    ],
  },
];

function newThread(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID().replaceAll("-", "").slice(0, 24)
    : String(Date.now());
}

export default function ResearchPage() {
  return (
    <Suspense fallback={null}>
      <Research />
    </Suspense>
  );
}

function Research() {
  const params = useSearchParams();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [activeCategory, setActiveCategory] = useState<string>("Key Ratios & Margins");
  const [experiment, setExperiment] = useState("E");
  const [thread, setThread] = useState<string>("");
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // "/" focuses the question box; Escape clears the highlighted citation.
  useKeydown((e) => {
    if (e.key === "/" && !isTyping(e) && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      inputRef.current?.focus();
    } else if (e.key === "Escape" && !isTyping(e)) {
      setActive(null);
    }
  });

  // grow the textarea with its content, up to the CSS max height
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [draft]);

  // clicking an evidence card brings its citation chip into view in the answer
  useEffect(() => {
    if (!active || !selected) return;
    document.querySelector(`[data-turn="${selected}"] [data-cite="${active}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [active, selected]);

  useEffect(() => {
    setThread(newThread());
    api.suggestions().then(setSuggestions).catch(() => setSuggestions([]));
  }, []);

  // ?q= asks once per distinct value, so the command palette can send new questions while this page is open
  const askedQ = useRef<string | null>(null);
  useEffect(() => {
    const q = params.get("q");
    if (q && thread && !busy && askedQ.current !== q) {
      askedQ.current = q;
      ask(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params, thread, busy]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length]);

  const current = useMemo(() => turns.find((t) => t.id === selected)?.answer ?? null, [turns, selected]);
  const lastAnswered = [...turns].reverse().find((t) => t.answer);
  const followUps = useMemo(() => {
    if (!lastAnswered?.answer || busy) return [];
    const asked = new Set(turns.map((t) => t.question.toLowerCase()));
    const plan = lastAnswered.answer.plan;
    const derived: string[] = [];
    if (plan.tickers.length && plan.query_type !== "unanswerable") {
      derived.push("How did that change versus the prior fiscal year?");
      derived.push("What does management say drove this in MD&A?");
      if (plan.tickers.length === 1) derived.push("How does that compare with the other companies?");
    }
    return [...derived, ...suggestions].filter((s) => !asked.has(s.toLowerCase())).slice(0, 5);
  }, [lastAnswered, suggestions, turns, busy]);

  function editQuestion(q: string) {
    setDraft(q);
    requestAnimationFrame(() => {
      const el = inputRef.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(q.length, q.length);
    });
  }

  async function ask(q: string, retryId?: string) {
    const question = q.trim();
    if (question.length < 3 || busy) return;
    const id = retryId ?? `${Date.now()}`;
    setTurns((t) => (retryId ? t.map((x) => (x.id === retryId ? { id, question } : x)) : [...t, { id, question }]));
    if (!retryId) setDraft("");
    setBusy(true);
    try {
      const answer = await api.query(question, thread, experiment);
      setTurns((t) => t.map((x) => (x.id === id ? { ...x, answer } : x)));
      setSelected(id);
      setActive(null);
    } catch (e) {
      const msg =
        e instanceof ApiError && e.status === 429
          ? "Too many questions in a minute. Wait a moment and ask again."
          : e instanceof Error
          ? e.message
          : "Request failed";
      setTurns((t) => t.map((x) => (x.id === id ? { ...x, error: msg } : x)));
    } finally {
      setBusy(false);
    }
  }

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const exportMarkdown = (turn: Turn) => {
    if (!turn.answer) return;
    const a = turn.answer;
    const content = `# Question: ${turn.question}\n\n**Verdict:** ${a.verification.verdict}\n**Latency:** ${a.latency_ms} ms | **Pipeline:** ${a.experiment}\n\n## Answer\n\n${a.answer}\n\n## Verified Evidence\n- Reported facts: ${a.facts.length}\n- Calculations: ${a.calculations.length}\n- 10-K passages: ${a.passages.length}\n\nGenerated by SEC 10-K Verifiable Intelligence Platform.`;
    const blob = new Blob([content], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const elem = document.createElement("a");
    elem.href = url;
    elem.download = `sec-research-${turn.id}.md`;
    elem.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="mx-auto grid max-w-7xl grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_440px]">
      <div className="flex min-h-[calc(100vh-3rem)] flex-col">
        {/* Header Bar */}
        <div className="flex flex-wrap items-end justify-between gap-3 border-b border-[var(--rule)] pb-4">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="font-serif text-[32px] font-semibold leading-tight">Research assistant</h1>
              <span className="rounded-full bg-[var(--accent-soft)] px-2.5 py-0.5 text-xs font-semibold text-[var(--accent)]">
                Live SEC XBRL
              </span>
            </div>
            <p className="mt-1 text-sm text-[var(--ink-2)]">
              Auditable 10-K financial answers. Hover citations for instant source preview, or click to inspect full proof.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs font-medium text-[var(--muted)]" htmlFor="exp">
              Pipeline:
            </label>
            <select
              id="exp"
              className="field text-xs font-medium"
              value={experiment}
              onChange={(e) => setExperiment(e.target.value)}
            >
              {EXPERIMENTS.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.label}
                </option>
              ))}
            </select>
            {turns.length > 0 && (
              <button
                className="btn text-xs hover:border-[var(--accent)]"
                onClick={() => {
                  setTurns([]);
                  setSelected(null);
                  setThread(newThread());
                }}
              >
                Reset thread
              </button>
            )}
          </div>
        </div>

        {/* Conversation Stream */}
        <div className="mt-6 flex-1 space-y-8">
          {turns.length === 0 && (
            <div className="panel p-6 shadow-sm">
              <div className="flex items-center justify-between border-b border-[var(--rule)] pb-3">
                <div>
                  <h2 className="font-serif text-xl font-semibold">Suggested Financial Inquiries</h2>
                  <p className="mt-0.5 text-xs text-[var(--muted)]">
                    Apple, Microsoft & NVIDIA (FY2023–2025). Tagged numbers are matched to SEC filings.
                  </p>
                </div>
              </div>

              {/* Category tabs */}
              <div className="mt-4 flex flex-wrap gap-2">
                {CURATED_CATEGORIES.map((cat) => (
                  <button
                    key={cat.name}
                    onClick={() => setActiveCategory(cat.name)}
                    className={`rounded-full px-3 py-1 text-xs font-medium transition-all ${
                      activeCategory === cat.name
                        ? "bg-[var(--accent)] text-[var(--accent-ink)] shadow-sm"
                        : "border border-[var(--rule)] text-[var(--ink-2)] hover:bg-[var(--panel-2)]"
                    }`}
                  >
                    {cat.name}
                  </button>
                ))}
              </div>

              {/* Categorized queries */}
              <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
                {CURATED_CATEGORIES.find((c) => c.name === activeCategory)?.queries.map((q) => (
                  <button
                    key={q}
                    onClick={() => ask(q)}
                    disabled={busy}
                    className="group flex items-start gap-2 rounded-lg border border-[var(--rule)] p-3 text-left text-xs font-medium transition-all hover:border-[var(--accent)] hover:bg-[var(--accent-soft)] hover:shadow-xs"
                  >
                    <span className="text-[var(--accent)] group-hover:translate-x-0.5 transition-transform">→</span>
                    <span className="text-[var(--ink)]">{q}</span>
                  </button>
                ))}
              </div>

              {suggestions.length > 0 && (
                <div className="mt-5 border-t border-[var(--rule)] pt-4">
                  <div className="text-[11px] font-semibold uppercase tracking-wider text-[var(--muted)]">Suggested from the indexed filings</div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {suggestions.slice(0, 8).map((s) => (
                      <button key={s} className="chip" onClick={() => ask(s)} disabled={busy}>
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <p className="mt-4 text-[11px] text-[var(--muted)]">
                Tip: press <kbd>/</kbd> to jump to the question box, or <kbd>Ctrl</kbd> <kbd>K</kbd> from any page.
              </p>
            </div>
          )}

          {turns.map((t) => (
            <article
              key={t.id}
              data-turn={t.id}
              className={`rise rounded-xl transition-all ${selected === t.id ? "" : "opacity-95"}`}
              onClick={() => t.answer && setSelected(t.id)}
            >
              <div className="group flex items-center gap-2">
                <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-[var(--ink)] text-[10px] font-semibold text-[var(--panel)]">
                  Q
                </span>
                <h2 className="text-[16px] font-semibold tracking-tight">{t.question}</h2>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    editQuestion(t.question);
                  }}
                  className="ml-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium text-[var(--muted)] opacity-0 transition-opacity hover:bg-[var(--panel-2)] hover:text-[var(--accent)] focus-visible:opacity-100 group-hover:opacity-100"
                  title="Copy this question into the box to refine it"
                >
                  Edit & re-ask
                </button>
              </div>

              {!t.answer && !t.error && <AgentProgressStepper />}
              {t.error && (
                <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[var(--fail)] bg-[var(--fail-soft)] p-4 text-sm text-[var(--fail)] shadow-xs">
                  <span>
                    <strong>Query Error:</strong> {t.error}
                  </span>
                  <button
                    type="button"
                    className="btn !py-1 text-xs"
                    disabled={busy}
                    onClick={(e) => {
                      e.stopPropagation();
                      ask(t.question, t.id);
                    }}
                  >
                    Retry
                  </button>
                </div>
              )}

              {t.answer && (
                <div
                  className={`panel mt-3 p-5 shadow-sm transition-all ${
                    selected === t.id ? "ring-2 ring-[var(--accent)] shadow-md" : "hover:border-[var(--rule-strong)]"
                  }`}
                >
                  {/* Top Bar with Verdict & Verification Metrics */}
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2 border-b border-[var(--rule)] pb-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <VerdictBadge verdict={t.answer.verification.verdict} />
                      <span className="num text-xs text-[var(--muted)]">
                        {t.answer.verification.numbers_total > 0 && (
                          <>
                            <strong>{t.answer.verification.numbers_supported}/{t.answer.verification.numbers_total}</strong> numbers audited ·{" "}
                          </>
                        )}
                        <strong>{t.answer.verification.citations_valid}/{t.answer.verification.citations_total}</strong> citations verified
                      </span>
                    </div>

                    {/* Quick Action Tools */}
                    <div className="flex items-center gap-1.5 text-xs">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          copyToClipboard(t.answer!.answer, `ans-${t.id}`);
                        }}
                        className="rounded-md border border-[var(--rule)] px-2.5 py-1 text-[var(--ink-2)] hover:border-[var(--accent)] hover:text-[var(--accent)]"
                        title="Copy answer markdown"
                      >
                        {copiedId === `ans-${t.id}` ? "Copied!" : "Copy"}
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          const url = `${window.location.origin}/research?q=${encodeURIComponent(t.question)}`;
                          copyToClipboard(url, `link-${t.id}`);
                        }}
                        className="rounded-md border border-[var(--rule)] px-2.5 py-1 text-[var(--ink-2)] hover:border-[var(--accent)] hover:text-[var(--accent)]"
                        title="Copy shareable link"
                      >
                        {copiedId === `link-${t.id}` ? "Link copied!" : "Share"}
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          exportMarkdown(t);
                        }}
                        className="rounded-md border border-[var(--rule)] px-2.5 py-1 text-[var(--ink-2)] hover:border-[var(--accent)] hover:text-[var(--accent)]"
                        title="Export to Markdown"
                      >
                        Export .md
                      </button>
                    </div>
                  </div>

                  {/* Answer Text with Interactive Popovers */}
                  <AnswerText
                    text={t.answer.answer}
                    answer={t.answer}
                    active={selected === t.id ? active : null}
                    onCite={(id) => {
                      setSelected(t.id);
                      setActive(id);
                    }}
                  />

                  {/* Limitations Callout */}
                  {t.answer.limitations.length > 0 && (
                    <div className="mt-4 rounded-lg border-l-4 border-[var(--warn)] bg-[var(--warn-soft)] p-3 text-xs text-[var(--ink)]">
                      <div className="mb-1 font-semibold flex items-center gap-1.5">
                        <span>Notice & Limitations</span>
                      </div>
                      <ul className="list-disc space-y-0.5 pl-4 text-[var(--ink-2)]">
                        {t.answer.limitations.slice(0, 6).map((l, i) => (
                          <li key={i}>{l}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Execution Trace Collapsible */}
                  <details className="mt-4 group border-t border-[var(--rule)] pt-3">
                    <summary className="flex cursor-pointer select-none items-center justify-between text-xs font-semibold text-[var(--ink-2)] hover:text-[var(--accent)]">
                      <span>Execution Trace & Verifier Log ({t.answer.trace.length} operations)</span>
                      <span className="text-[10px] text-[var(--muted)] group-open:rotate-180 transition-transform">▼</span>
                    </summary>
                    <div className="mt-3">
                      <Trace events={t.answer.trace} />
                    </div>
                  </details>

                  {/* Metadata Footer */}
                  <div className="num mt-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-[var(--rule)] pt-3 text-xs text-[var(--muted)]">
                    <div className="flex items-center gap-3">
                      <span>{ms(t.answer.latency_ms)}</span>
                      <span>·</span>
                      <span>
                        {t.answer.usage.provider === "offline"
                          ? "Offline Synthesizer ($0)"
                          : `${t.answer.usage.model} (${t.answer.usage.input_tokens + t.answer.usage.output_tokens} tokens)`}
                      </span>
                      <span>·</span>
                      <span>Pipeline {t.answer.experiment}</span>
                    </div>
                    <Link
                      href={`/inspector?run=${t.answer.run_id}`}
                      className="font-medium text-[var(--accent)] hover:underline"
                    >
                      Audit run in Inspector →
                    </Link>
                  </div>
                </div>
              )}
            </article>
          ))}

          {followUps.length > 0 && (
            <div className="rise" aria-label="Follow-up questions">
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--muted)]">Follow up</div>
              <div className="flex flex-wrap gap-1.5">
                {followUps.map((s) => (
                  <button key={s} className="chip" onClick={() => ask(s)}>
                    <span className="text-[var(--accent)]">↳</span> {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          <div ref={endRef} />
        </div>

        {/* Sticky Question Input Bar */}
        <form
          className="sticky bottom-0 mt-6 bg-[var(--paper)] pb-4 pt-2"
          onSubmit={(e) => {
            e.preventDefault();
            ask(draft);
          }}
        >
          <div className="panel flex items-end gap-2 p-2 shadow-lg ring-1 ring-[var(--rule-strong)] focus-within:ring-2 focus-within:ring-[var(--accent)] transition-all">
            <textarea
              ref={inputRef}
              className="max-h-40 min-h-[46px] flex-1 resize-none overflow-y-auto bg-transparent px-3 py-2 text-[15px] outline-none placeholder:text-[var(--muted)]"
              placeholder="Ask about revenue, margins, free cash flow, risks, accounting policies..."
              aria-label="Question"
              value={draft}
              maxLength={1000}
              rows={1}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  ask(draft);
                } else if (e.key === "ArrowUp" && !draft && turns.length) {
                  e.preventDefault();
                  editQuestion(turns[turns.length - 1].question);
                } else if (e.key === "Escape") {
                  e.currentTarget.blur();
                }
              }}
            />
            <button
              type="submit"
              className="btn btn-primary px-4 py-2 text-sm shadow-sm transition-all"
              disabled={busy || draft.trim().length < 3}
            >
              {busy ? (
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 animate-ping rounded-full bg-white" />
                  Auditing...
                </span>
              ) : (
                "Ask 10-K"
              )}
            </button>
          </div>
          <div className="mt-1.5 flex items-center justify-between px-1 text-[11px] text-[var(--muted)]">
            <span>
              <kbd>Enter</kbd> ask · <kbd>Shift</kbd>+<kbd>Enter</kbd> newline · <kbd>↑</kbd> recall last question
            </span>
            <span className="flex items-center gap-3">
              {draft.length > 800 && <span className={draft.length >= 1000 ? "text-[var(--fail)]" : ""}>{draft.length}/1000</span>}
              {turns.length > 0 && <span className="hidden sm:inline">Thread retains context across follow-up queries</span>}
            </span>
          </div>
        </form>
      </div>

      {/* Right Column: Evidence Inspector Panel */}
      <aside className="xl:sticky xl:top-6 xl:h-[calc(100vh-3rem)] xl:overflow-y-auto" aria-label="Evidence">
        <div className="panel p-4 shadow-sm">
          <div className="flex items-center justify-between border-b border-[var(--rule)] pb-3">
            <div>
              <h2 className="font-serif text-lg font-semibold">Proven Evidence</h2>
              <p className="text-xs text-[var(--muted)]">XBRL facts, Python Decimal computations & 10-K text</p>
            </div>
            {current && (
              <span className="num rounded-full bg-[var(--panel-2)] px-2 py-0.5 text-xs font-semibold text-[var(--ink-2)]">
                {current.facts.length + current.calculations.length + current.passages.length} items
              </span>
            )}
          </div>
          {current ? (
            <div className="mt-4">
              <EvidencePanel answer={current} active={active} onCite={setActive} />
            </div>
          ) : (
            <div className="mt-8 text-center text-sm text-[var(--muted)]">
              <div className="mx-auto mb-2 grid h-12 w-12 place-items-center rounded-full bg-[var(--panel-2)] text-xl">
                📑
              </div>
              <p className="font-medium text-[var(--ink-2)]">No query selected</p>
              <p className="mt-1 text-xs">
                Ask a question to see its audited XBRL facts, formulas and citations here.
              </p>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

function AgentProgressStepper() {
  const stages = [
    { label: "Classifying query scope & routing", icon: "🔍" },
    { label: "Extracting SEC XBRL facts & computing metrics", icon: "📊" },
    { label: "Executing hybrid semantic retrieval (BM25 + Qdrant)", icon: "📖" },
    { label: "Auditing numbers, citations & verification constraints", icon: "🛡️" },
  ];
  const [activeStage, setActiveStage] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setActiveStage((prev) => Math.min(prev + 1, stages.length - 1));
    }, 850);
    return () => clearInterval(timer);
  }, [stages.length]);

  return (
    <div className="panel mt-3 p-4 shadow-sm animate-pulse">
      <div className="space-y-2">
        {stages.map((st, idx) => (
          <div
            key={st.label}
            className={`flex items-center gap-3 text-xs transition-opacity ${
              idx === activeStage
                ? "font-semibold text-[var(--accent)] opacity-100"
                : idx < activeStage
                ? "text-[var(--ok)] opacity-80"
                : "text-[var(--muted)] opacity-40"
            }`}
          >
            <span className="text-sm">{idx < activeStage ? "✓" : st.icon}</span>
            <span>{st.label}</span>
            {idx === activeStage && (
              <span className="h-1.5 w-1.5 animate-ping rounded-full bg-[var(--accent)]" />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
