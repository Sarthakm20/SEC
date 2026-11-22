// Typed client for the FastAPI backend (proxied through Next.js at /api).

export type Verdict = "verified" | "partially_verified" | "insufficient_evidence" | "failed";

export interface FactLocation {
  page: number | null;
  table_title: string | null;
  row_label: string | null;
  displayed_value: string | null;
}

export interface Fact {
  id: string;
  ticker: string;
  concept: string;
  label: string;
  value: string;
  unit: string;
  period_type: "duration" | "instant";
  start: string | null;
  end: string;
  fiscal_year: number;
  accession: string;
  filed: string;
  source_url: string | null;
  location: FactLocation | null;
  evidence_id: string | null;
}

export interface CalcInput {
  name: string;
  fact_id: string | null;
  evidence_id: string | null;
  concept: string | null;
  value: string;
  unit: string;
  start: string | null;
  end: string;
  fiscal_year: number;
}

export interface Calculation {
  id: string;
  evidence_id: string | null;
  metric: string;
  label: string;
  ticker: string;
  fiscal_year: number;
  formula: string;
  inputs: CalcInput[];
  result: string;
  result_unit: string;
  display: string;
  definition: string | null;
  warnings: string[];
}

export interface Chunk {
  id: string;
  ticker: string;
  fiscal_year: number;
  accession: string;
  filing_date: string;
  section: string;
  section_title: string;
  subsection: string | null;
  kind: "text" | "table";
  text: string;
  page_start: number | null;
  page_end: number | null;
  source_url: string;
  injection_flags: string[];
}

export interface Passage {
  chunk: Chunk;
  evidence_id: string | null;
  scores: {
    bm25_rank: number | null;
    bm25_score: number | null;
    dense_rank: number | null;
    dense_score: number | null;
    rrf_score: number | null;
    rerank_score: number | null;
  };
}

export interface ClaimCheck {
  sentence: string;
  status: "verified_fact" | "calculated" | "interpretation" | "unsupported";
  citations: string[];
  numbers: string[];
  support_score: number | null;
  issues: string[];
}

export interface Verification {
  verdict: Verdict;
  citations_total: number;
  citations_valid: number;
  invalid_citations: string[];
  numbers_total: number;
  numbers_supported: number;
  unsupported_numbers: string[];
  period_issues: string[];
  conflicts: string[];
  claims: ClaimCheck[];
  recomputed_calculations: number;
  notes: string[];
}

export interface TraceEvent {
  step: string;
  label: string;
  status: "ok" | "warn" | "error" | "skip";
  duration_ms: number;
  detail: Record<string, unknown>;
}

export interface Plan {
  query_type: string;
  tickers: string[];
  fiscal_years: number[];
  metrics: string[];
  sections: string[];
  planner: string;
  notes: string[];
}

export interface Answer {
  run_id: string;
  question: string;
  answer: string;
  plan: Plan;
  facts: Fact[];
  calculations: Calculation[];
  passages: Passage[];
  verification: Verification;
  trace: TraceEvent[];
  usage: { provider: string; model: string; input_tokens: number; output_tokens: number; llm_calls: number; estimated_cost_usd: number };
  limitations: string[];
  latency_ms: number;
  experiment: string;
}

export interface MetricValue {
  metric: string;
  label: string;
  ticker: string;
  fiscal_year: number;
  kind: string;
  value: string | null;
  display: string | null;
  unit: string | null;
  period_start: string | null;
  period_end: string | null;
  fact: Fact | null;
  calculation: Calculation | null;
  warnings: string[];
  error: string | null;
}

export interface Filing {
  accession: string;
  fiscal_year: number;
  filing_date: string;
  report_date: string;
  url: string;
  index_url: string;
  n_chunks: number;
  n_facts_located: number;
  sections: Record<string, { title: string; page_start: string | null; page_end: string | null; chunks: number }>;
}

export interface Company {
  ticker: string;
  cik: number;
  name: string;
  fiscal_year_end: string | null;
  years: { facts: number[]; filings: number[] };
  filings: Filing[];
}

export interface Overview {
  company: { ticker: string; name: string; cik: number; fiscal_year_end: string | null };
  fiscal_year: number;
  kpis: (MetricValue & { yoy: string | null })[];
  ratios: MetricValue[];
  trend: { fiscal_year: number; revenue: number | null; net_income: number | null; operating_cash_flow: number | null; free_cash_flow: number | null }[];
  filing: Filing | null;
}

export interface Comparison {
  fiscal_year: number;
  align: "fiscal" | "calendar";
  resolved_fiscal_years: Record<string, number>;
  rows: { metric: string; label: string; values: Record<string, MetricValue> }[];
  period_notes: string[];
}

export interface RunSummary {
  run_id: string;
  created_at: string;
  question: string;
  verdict: Verdict;
  experiment: string;
  latency_ms: number;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ llm: { provider: string; model: string }; chunks: number; companies: string[]; reranker: string | null; embedding: string }>("/api/health"),
  companies: () => request<Company[]>("/api/companies"),
  overview: (ticker: string, fy?: number) => request<Overview>(`/api/companies/${ticker}/overview${fy ? `?fiscal_year=${fy}` : ""}`),
  compare: (tickers: string[], fy: number, align: "fiscal" | "calendar") =>
    request<Comparison>(`/api/compare?tickers=${tickers.join(",")}&fiscal_year=${fy}&align=${align}`),
  query: (question: string, threadId?: string, experiment = "E") =>
    request<Answer>("/api/query", { method: "POST", body: JSON.stringify({ question, thread_id: threadId, experiment }) }),
  runs: (limit = 40) => request<RunSummary[]>(`/api/runs?limit=${limit}`),
  run: (id: string) => request<Answer>(`/api/runs/${id}`),
  suggestions: () => request<string[]>("/api/suggestions"),
  evalLatest: () => request<BenchmarkReport>("/api/eval/latest"),
  evalGold: () => request<GoldCrosscheck>("/api/eval/gold"),
};

/** Result of `python -m evaluation.crosscheck_gold`: gold answers matched against SEC XBRL, independent of the QA pipeline. */
export interface GoldCrosscheck {
  created_at: string;
  questions: number;
  reported_checked: number;
  matched: number;
  mismatched: number;
  derived_for_review: number;
  mismatches: { question_id: string; label: string; value: string; tickers: string[]; fiscal_years: number[] }[];
  gold_sha256: string;
  stale: boolean;
}

export interface BenchmarkReport {
  created_at: string;
  questions: number;
  k: number;
  llm: { provider: string; model: string };
  embedding: string;
  reranker: string | null;
  corpus_chunks: number;
  experiments: Record<string, { description: string; reader?: string; summary: Record<string, unknown> }>;
}
