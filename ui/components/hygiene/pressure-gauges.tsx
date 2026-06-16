import { MonoLabel } from "@/components/ui/mono-label";
import { Card } from "@/components/ui/card";
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
      className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--surface-1)]"
    >
      <div
        className="h-full rounded-full transition-[width] duration-[var(--dur-med)]"
        style={{ width: `${pct}%`, background: color, boxShadow: `0 0 8px ${color}` }}
      />
    </div>
  );
}

export function PressureGauges({ data }: Props) {
  const totalFlagged =
    data.flagged.stale_working_count + data.flagged.low_value_count + data.flagged.contradiction_count;
  return (
    <Card variant="flat" className="grid grid-cols-1 gap-6 md:grid-cols-3">
      <div className="space-y-2">
        <MonoLabel>load score</MonoLabel>
        <div className="font-mono text-3xl text-[var(--fg)]">{data.load_score.toFixed(2)}</div>
        <GaugeBar value={data.load_score} max={1} color="var(--accent-primary)" />
      </div>
      <div className="space-y-2">
        <MonoLabel>capacity</MonoLabel>
        <div className="font-mono text-3xl text-[var(--fg)]">{data.capacity}</div>
        <GaugeBar value={Math.min(data.capacity, 2000)} max={2000} color="var(--accent-secondary)" />
      </div>
      <div className="space-y-2">
        <MonoLabel>flagged</MonoLabel>
        <div className="font-mono text-3xl text-[var(--fg)]">{totalFlagged}</div>
        <div className="flex gap-4 text-[11px] font-mono text-[var(--fg-muted)]">
          <span>stale {data.flagged.stale_working_count}</span>
          <span>low {data.flagged.low_value_count}</span>
          <span>conflict {data.flagged.contradiction_count}</span>
        </div>
      </div>
    </Card>
  );
}
