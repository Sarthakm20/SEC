"use client";

import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { seriesVar } from "@/lib/format";

const axis = { stroke: "var(--rule)", tick: { fill: "var(--muted)", fontSize: 12 }, tickLine: false };

function TooltipBox({
  active,
  payload,
  label,
  fmt,
  hint,
}: {
  active?: boolean;
  payload?: { name: string; value: number; color: string; payload?: { ticker?: string } }[];
  label?: string | number;
  fmt: (v: number) => string;
  hint?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-[var(--rule)] bg-[var(--panel)] px-3 py-2 text-xs shadow-sm">
      <div className="mb-1 font-medium">{label}</div>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-2">
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: p.payload?.ticker ? seriesVar(p.payload.ticker) : p.color }} />
          <span className="text-[var(--ink-2)]">{p.name}</span>
          <span className="num ml-auto pl-3 font-medium">{fmt(p.value)}</span>
        </div>
      ))}
      {hint && <div className="mt-1 border-t border-[var(--rule)] pt-1 text-[10px] text-[var(--muted)]">{hint}</div>}
    </div>
  );
}

/**
 * Multi-year trend. Both series share one unit (USD billions) so a single axis is honest.
 * `activeLabel` marks the selected year; `onSelect` makes points clickable (e.g. to switch fiscal year).
 */
export function TrendChart({
  data,
  series,
  activeLabel,
  onSelect,
  height = "h-64",
}: {
  data: Record<string, number | string | null>[];
  series: { key: string; name: string; color: string }[];
  activeLabel?: string;
  onSelect?: (label: string) => void;
  height?: string;
}) {
  const fmt = (v: number) => `$${v.toFixed(1)}B`;
  return (
    <div className={`${height} w-full ${onSelect ? "cursor-pointer" : ""}`} role="img" aria-label={`Trend of ${series.map((s) => s.name).join(" and ")} by fiscal year`}>
      <ResponsiveContainer>
        <LineChart
          data={data}
          margin={{ top: 10, right: 16, bottom: 0, left: 0 }}
          onClick={(st: unknown) => {
            const label = (st as { activeLabel?: string | number } | null)?.activeLabel;
            if (onSelect && label !== undefined) onSelect(String(label));
          }}
        >
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          {activeLabel && <ReferenceLine x={activeLabel} stroke="var(--rule-strong)" strokeDasharray="3 3" />}
          <XAxis dataKey="label" {...axis} />
          <YAxis {...axis} axisLine={false} width={56} tickFormatter={(v) => `$${v}B`} />
          <Tooltip content={<TooltipBox fmt={fmt} hint={onSelect ? "Click to view this year" : undefined} />} cursor={{ stroke: "var(--rule-strong)" }} />
          {series.map((s) => (
            <Line
              key={s.key}
              isAnimationActive
              animationDuration={500}
              dataKey={s.key}
              name={s.name}
              stroke={s.color}
              strokeWidth={2}
              dot={(props: unknown) => {
                const p = props as { cx?: number; cy?: number; index: number; payload: { label: string } };
                if (p.cx === undefined || p.cy === undefined) return <g key={p.index} />;
                const on = p.payload.label === activeLabel;
                return <circle key={p.index} cx={p.cx} cy={p.cy} r={on ? 6 : 4} strokeWidth={2} stroke="var(--panel)" fill={s.color} />;
              }}
              activeDot={{ r: 7, strokeWidth: 2, stroke: "var(--panel)" }}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** One metric across pipelines. The selected pipeline is drawn in accent, the rest in a quiet neutral. */
export function PipelineBars({
  data,
  fmt,
  label,
  selected,
  onSelect,
}: {
  data: { id: string; value: number }[];
  fmt: (v: number) => string;
  label: string;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="h-60 w-full" role="img" aria-label={`${label} by pipeline`}>
      <ResponsiveContainer>
        <BarChart
          data={data}
          margin={{ top: 22, right: 8, bottom: 0, left: 0 }}
          barCategoryGap="28%"
          onClick={(st: unknown) => {
            const l = (st as { activeLabel?: string } | null)?.activeLabel;
            if (l !== undefined) onSelect(String(l));
          }}
        >
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="id" {...axis} tickFormatter={(v) => `Pipeline ${v}`} />
          <YAxis {...axis} axisLine={false} width={56} tickFormatter={fmt} />
          <Tooltip content={<TooltipBox fmt={fmt} />} cursor={{ fill: "var(--panel-2)" }} />
          <Bar
            isAnimationActive
            animationDuration={450}
            dataKey="value"
            name={label}
            radius={[4, 4, 0, 0]}
            maxBarSize={64}
            className="cursor-pointer"
            label={{ position: "top", fill: "var(--ink-2)", fontSize: 12, formatter: (v: unknown) => fmt(Number(v)) }}
          >
            {data.map((d) => (
              <Cell key={d.id} fill={d.id === selected ? "var(--accent)" : "var(--rule-strong)"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/**
 * One measure per chart (never dual-axis); bar color follows the company.
 * A null value keeps the company on the x-axis with no bar; tickers in `dim` (not selected) get a faded label.
 */
export function CompareBars({
  data,
  unit,
  label,
  dim = [],
}: {
  data: { ticker: string; value: number | null }[];
  unit: "percent" | "usd" | "ratio";
  label: string;
  dim?: string[];
}) {
  const fmt = (v: number | null) =>
    v === null || v === undefined || Number.isNaN(v)
      ? "—"
      : unit === "percent"
      ? `${(v * 100).toFixed(1)}%`
      : unit === "usd"
      ? `$${(v / 1e9).toFixed(1)}B`
      : v.toFixed(2);
  const tick = (props: unknown) => {
    const p = props as { x: number; y: number; payload: { value: string } };
    const off = dim.includes(p.payload.value);
    return (
      <text x={p.x} y={p.y + 12} textAnchor="middle" fontSize={12} fill="var(--muted)" opacity={off ? 0.45 : 1}>
        {p.payload.value}
      </text>
    );
  };
  return (
    <div className="h-64 w-full" role="img" aria-label={`${label} by company`}>
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 18, right: 8, bottom: 0, left: 0 }} barCategoryGap="30%">
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="ticker" {...axis} tick={tick} interval={0} />
          <YAxis {...axis} axisLine={false} width={56} tickFormatter={fmt} />
          <Tooltip content={<TooltipBox fmt={fmt} />} cursor={{ fill: "var(--panel-2)" }} />
          <Bar
            isAnimationActive
            animationDuration={450}
            dataKey="value"
            name={label}
            radius={[4, 4, 0, 0]}
            maxBarSize={56}
            label={{ position: "top", fill: "var(--ink-2)", fontSize: 12, formatter: (v: unknown) => (v === null || v === undefined ? "" : fmt(Number(v))) }}
            shape={(props: unknown) => {
              const p = props as { x: number; y: number; width: number; height: number; payload: { ticker: string; value: number | null } };
              if (p.payload.value === null || !Number.isFinite(p.height)) return <g />;
              const h = Math.max(p.height, 0);
              const r = Math.min(4, h);
              const { x, y, width: w } = p;
              return <path d={`M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`} fill={seriesVar(p.payload.ticker)} />;
            }}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
