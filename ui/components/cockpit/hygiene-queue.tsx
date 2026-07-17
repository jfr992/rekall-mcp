import Link from "next/link";
import { MonoLabel } from "@/components/ui/mono-label";
import type { PressureResponse } from "@/lib/schemas";

type Props = {
  pressure: PressureResponse | undefined;
};

export function HygieneQueue({ pressure }: Props) {
  const flagged = pressure?.flagged;

  const items = flagged
    ? [
        {
          count: flagged.stale_working_count,
          label: "working memories decaying",
          color: "var(--accent-danger)",
          border: "rgba(248,113,113,0.3)",
        },
        {
          count: flagged.low_value_count,
          label: "low-value memories to review",
          color: "var(--accent-warning)",
          border: "rgba(242,193,78,0.3)",
        },
        {
          count: flagged.contradiction_count,
          label: "contradictions detected",
          color: "var(--fg-muted)",
          border: "rgba(125,200,170,0.2)",
        },
      ]
    : [];

  return (
    <section className="rounded-[11px] border border-[var(--border)] bg-[var(--bg-elevated)] px-4 py-4">
      <MonoLabel className="mb-2.5 block text-[9px] tracking-[0.16em]">Hygiene queue</MonoLabel>

      {flagged ? (
        <ul className="flex flex-col gap-2 text-xs text-[var(--fg-soft)]">
          {items.map((item) => (
            <li key={item.label} className="flex items-center gap-2">
              <span
                className="rounded px-1.5 py-px font-mono text-[10px] font-medium"
                style={{ color: item.color, border: `1px solid ${item.border}` }}
              >
                {item.count}
              </span>
              {item.label}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-[var(--fg-dim)]">pressure unavailable</p>
      )}

      <Link
        href="/hygiene"
        className="mt-3 inline-block text-xs text-[var(--accent-bright)] hover:text-[var(--fg)]"
      >
        Review →
      </Link>
    </section>
  );
}
