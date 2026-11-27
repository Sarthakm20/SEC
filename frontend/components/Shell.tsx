"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Backdrop } from "./Backdrop";
import { CommandPalette } from "./CommandPalette";

const NAV = [
  { href: "/", label: "Overview", icon: "M3 13h4v8H3zM10 9h4v12h-4zM17 4h4v17h-4z" },
  { href: "/research", label: "Research Assistant", icon: "M4 5h16v11H8l-4 4z" },
  { href: "/compare", label: "Compare", icon: "M5 4v16M12 8v12M19 12v8" },
  { href: "/inspector", label: "Inspector", icon: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM16 16l5 5" },
  { href: "/benchmark", label: "Benchmark & Ablation", icon: "M4 20h16M7 16l3-5 3 3 4-7" },
];

function Icon({ d }: { d: string }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={d} />
    </svg>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [health, setHealth] = useState<{ provider: string; model: string; chunks: number } | null>(null);
  const [down, setDown] = useState(false);

  useEffect(() => {
    api
      .health()
      .then((h) => setHealth({ provider: h.llm.provider, model: h.llm.model, chunks: h.chunks }))
      .catch(() => setDown(true));
  }, []);

  const formatProvider = (prov: string, model: string) => {
    if (prov === "offline") return "Deterministic (Offline $0)";
    if (prov === "gemini") return `Gemini (${model.replace("gemini-", "")})`;
    if (prov === "anthropic") return "Claude";
    if (prov === "openai") return `OpenAI (${model})`;
    return prov;
  };

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-16 shrink-0 flex-col border-r border-[var(--rule)] bg-[var(--panel)] px-2 py-4 lg:w-64 lg:px-4 shadow-xs">
        {/* Logo / Title */}
        <Link href="/" className="mb-6 flex items-center gap-2.5 px-2">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-[var(--ink)] font-serif text-[15px] font-bold text-[var(--panel)] shadow-xs">
            10K
          </span>
          <div className="hidden lg:block">
            <span className="block font-serif text-[17px] font-bold leading-none tracking-tight">
              SEC Financial Intelligence
            </span>
            <span className="text-[10px] uppercase tracking-wider text-[var(--muted)] font-semibold">
              Verifiable Agentic RAG
            </span>
          </div>
        </Link>

        {/* Navigation Links */}
        <nav className="flex flex-1 flex-col gap-1" aria-label="Main">
          {NAV.map((n) => {
            const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
            return (
              <Link
                key={n.href}
                href={n.href}
                aria-current={active ? "page" : undefined}
                className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all ${
                  active
                    ? "bg-[var(--accent-soft)] text-[var(--accent)] shadow-xs"
                    : "text-[var(--ink-2)] hover:bg-[var(--panel-2)] hover:text-[var(--ink)]"
                }`}
              >
                <Icon d={n.icon} />
                <span className="hidden lg:inline">{n.label}</span>
              </Link>
            );
          })}
        </nav>

        {/* Live Engine & Backend Status Widget */}
        <div className="mt-4 hidden border-t border-[var(--rule)] px-2 pt-3 text-xs lg:block">
          {down ? (
            <div className="rounded-md bg-[var(--fail-soft)] p-2.5 text-[var(--fail)]">
              <div className="flex items-center gap-1.5 font-semibold">
                <span className="h-2 w-2 rounded-full bg-[var(--fail)]" />
                Backend unreachable
              </div>
              <div className="mt-1 text-[11px] leading-tight">
                Start: <code>uvicorn app.api.main:app</code>
              </div>
            </div>
          ) : health ? (
            <div className="space-y-1.5 text-[var(--muted)]">
              <div className="flex items-center gap-1.5 text-[var(--ok)] font-medium">
                <span className="h-2 w-2 rounded-full bg-[var(--ok)] animate-pulse" />
                <span>Backend Connected</span>
              </div>
              <div className="text-[11px]">
                <strong className="text-[var(--ink)]">{health.chunks.toLocaleString()}</strong> 10-K passages indexed
              </div>
              <div className="text-[11px] truncate" title={health.model}>
                Engine: <strong className="text-[var(--ink)]">{formatProvider(health.provider, health.model)}</strong>
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-1.5 text-[var(--muted)]">
              <span className="h-2 w-2 rounded-full bg-[var(--muted)] animate-ping" />
              <span>Checking services...</span>
            </div>
          )}
        </div>

      </aside>

      {/* Main Content Area: the backdrop sits outside <main> so it doesn't replay the page transition */}
      <div className="relative isolate min-w-0 flex-1">
        <Backdrop />
        <main key={path} className="rise relative px-4 py-6 sm:px-8">
          {children}
        </main>
      </div>
      <CommandPalette />
    </div>
  );
}
