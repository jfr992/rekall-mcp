import { MonoLabel } from "@/components/ui/mono-label";
import type { PressureResponse } from "@/lib/schemas";

type Props = { data: PressureResponse };

function GaugeBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = Math.max(0, Math.min((value / max) * 100, 100));
  return (
    <div
      role="meter"
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={max}
      className="mt-3 h-1 w-full overflow-hidden rounded-full bg-[rgba(45,212,160,0.12)]"
    >
      <div
        className="h-full rounded-full transition-[width] duration-[var(--dur-med)]"
        style={{ width: `${pct}%`, background: color, boxShadow: `0 0 8px ${color}` }}
      />
    </div>
  );
}

function loadColor(score: number): string {
  if (score < 0.2) return "var(--accent-success)";
  if (score < 0.5) return "var(--accent-primary)";
  if (score < 0.8) return "var(--accent-warning)";
  return "var(--accent-danger)";
}

const statCard = "rounded-[11px] border bg-[var(--bg-elevated)] px-5 py-4";

export function PressureGauges({ data }: Props) {
  const totalFlagged =
    data.flagged.stale_working_count + data.flagged.low_value_count + data.flagged.contradiction_count;
  const load = loadColor(data.load_score);
  return (
    <div className="grid grid-cols-1 gap-3.5 md:grid-cols-3">
      <div className={`${statCard} border-[var(--border)]`}>
        <MonoLabel className="tracking-[0.16em]">load score</MonoLabel>
        <div className="mt-1.5 font-serif text-4xl leading-[1.1]" style={{ color: load }}>
          {data.load_score.toFixed(2)}
        </div>
        <GaugeBar value={data.load_score} max={1} color={load} />
      </div>
      <div className={`${statCard} border-[var(--border)]`}>
        <MonoLabel className="tracking-[0.16em]">capacity</MonoLabel>
        <div className="mt-1.5 font-serif text-4xl leading-[1.1] text-[var(--fg)]">
          {data.capacity}
        </div>
        <GaugeBar
          value={Math.min(data.capacity, 2000)}
          max={2000}
          color="var(--accent-primary)"
        />
      </div>
      <div className={`${statCard} border-[rgba(248,113,113,0.25)]`}>
        <MonoLabel className="tracking-[0.16em] text-[var(--accent-danger)]">flagged</MonoLabel>
        <div className="mt-1.5 font-serif text-4xl leading-[1.1] text-[var(--accent-danger)]">
          {totalFlagged}
        </div>
        <div className="mt-2.5 flex gap-3 font-mono text-[10.5px] text-[var(--fg-muted)]">
          <span>stale {data.flagged.stale_working_count}</span>
          <span>low {data.flagged.low_value_count}</span>
          <span className="text-[var(--accent-danger)]">
            conflict {data.flagged.contradiction_count}
          </span>
        </div>
      </div>
    </div>
  );
}
