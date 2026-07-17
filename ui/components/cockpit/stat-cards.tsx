import { MonoLabel } from "@/components/ui/mono-label";
import type { InsightsResponse, PressureResponse } from "@/lib/schemas";

type Props = {
  insights: InsightsResponse;
  pressure: PressureResponse | undefined;
};

function sparklinePath(counts: number[], width: number, height: number): string {
  if (counts.length === 0) return "";
  const max = Math.max(...counts, 1);
  const step = counts.length > 1 ? width / (counts.length - 1) : 0;
  return counts
    .map((c, i) => {
      const x = i * step;
      const y = height - (c / max) * (height - 2) - 1;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

function Sparkline({ counts }: { counts: number[] }) {
  const width = 120;
  const height = 34;
  return (
    <svg
      data-testid="sparkline"
      viewBox={`0 0 ${width} ${height}`}
      className="mt-3 h-[34px] w-full"
      preserveAspectRatio="none"
      role="img"
      aria-label="Memories created per week"
    >
      <path
        d={sparklinePath(counts, width, height)}
        fill="none"
        stroke="var(--accent-primary)"
        strokeWidth="1.5"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

export function StatCards({ insights, pressure }: Props) {
  const delta = insights.weekly_delta;
  const deltaLabel = `${delta >= 0 ? "+" : ""}${delta} this week`;

  return (
    <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 xl:grid-cols-[1.4fr_1fr_1fr_1fr]">
      <div className="rounded-[11px] border border-[rgba(45,212,160,0.25)] bg-[radial-gradient(ellipse_90%_140%_at_20%_0%,rgba(45,212,160,0.14),rgba(13,17,32,0.6))] px-5 py-4">
        <MonoLabel className="text-[9px] tracking-[0.16em]">Total memories</MonoLabel>
        <div className="mt-1.5 flex items-baseline gap-2.5">
          <span className="font-serif text-[44px] leading-none text-[var(--fg)]">
            {insights.total}
          </span>
          <span className="font-mono text-[11px] font-medium text-[var(--accent-success)]">
            {deltaLabel}
          </span>
        </div>
        <Sparkline counts={insights.per_week.map((w) => w.count)} />
      </div>

      <div className="rounded-[11px] border border-[var(--border)] bg-[var(--bg-elevated)] px-5 py-4">
        <MonoLabel className="text-[9px] tracking-[0.16em]">Recalls · 7d</MonoLabel>
        <div className="mt-1.5 font-serif text-4xl leading-[1.1] text-[var(--fg)]">
          {insights.recalls_7d}
        </div>
        <div
          className="mt-2 text-[11px] text-[var(--fg-muted)]"
          title={`mean over ${insights.avg_top_score_denominator} scored recalls`}
        >
          avg. top match{" "}
          <span className="font-mono text-[var(--accent-bright)]">
            {insights.avg_top_score_7d === null ? "—" : insights.avg_top_score_7d.toFixed(2)}
          </span>
        </div>
      </div>

      <div className="rounded-[11px] border border-[var(--border)] bg-[var(--bg-elevated)] px-5 py-4">
        <MonoLabel className="text-[9px] tracking-[0.16em]">Recalls with hits</MonoLabel>
        <div className="mt-1.5 font-serif text-4xl leading-[1.1] text-[var(--accent-success)]">
          {insights.recalls_7d > 0
            ? `${Math.round((insights.recalls_with_hits_7d / insights.recalls_7d) * 100)}%`
            : "—"}
        </div>
        <div className="mt-2 text-[11px] text-[var(--fg-muted)]">
          {insights.recalls_with_hits_7d} of {insights.recalls_7d} recalls with hits · 7d
        </div>
      </div>

      <div className="rounded-[11px] border border-[rgba(248,113,113,0.25)] bg-[var(--bg-elevated)] px-5 py-4">
        <MonoLabel className="text-[9px] tracking-[0.16em] text-[var(--accent-danger)]">
          Needs attention
        </MonoLabel>
        <div className="mt-1.5 font-serif text-4xl leading-[1.1] text-[var(--accent-danger)]">
          {pressure
            ? pressure.flagged.stale_working_count +
              pressure.flagged.low_value_count +
              pressure.flagged.contradiction_count
            : "—"}
        </div>
        <div className="mt-2 font-mono text-[10.5px] text-[var(--fg-muted)]">
          {pressure
            ? `stale ${pressure.flagged.stale_working_count} · low ${pressure.flagged.low_value_count} · conflict ${pressure.flagged.contradiction_count}`
            : "pressure unavailable"}
        </div>
      </div>
    </div>
  );
}
