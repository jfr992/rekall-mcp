import { MonoLabel } from "@/components/ui/mono-label";
import { tokens, type Tier } from "@/lib/theme";
import type { InsightsResponse } from "@/lib/schemas";

type Props = {
  insights: InsightsResponse;
};

// Ladder order, top tier first — matches the design source
const TIERS: Tier[] = ["identity", "semantic", "episodic", "working"];

export function TierComposition({ insights }: Props) {
  const counts = insights.tier_counts;
  const total = TIERS.reduce((s, t) => s + counts[t], 0);

  return (
    <section className="rounded-[11px] border border-[var(--border)] bg-[var(--bg-elevated)] px-5 py-4">
      <MonoLabel className="mb-4 block text-[9px] tracking-[0.16em]">Tier composition</MonoLabel>

      <div data-testid="tier-bar" className="mb-4 flex h-3 overflow-hidden rounded-md">
        {TIERS.map((tier) => (
          <div
            key={tier}
            style={{
              width: total > 0 ? `${(counts[tier] / total) * 100}%` : "25%",
              background: tokens.tier[tier],
            }}
          />
        ))}
      </div>

      <ul className="flex flex-col gap-2 text-xs text-[var(--fg-soft)]">
        {TIERS.map((tier) => (
          <li key={tier} className="flex items-center gap-2">
            <span
              className="h-2 w-2 rounded-[2px]"
              style={{ background: tokens.tier[tier] }}
              aria-hidden
            />
            <span>{tier}</span>
            <span className="ml-auto font-mono text-[11px] text-[var(--fg-muted)]">
              {counts[tier]}
            </span>
          </li>
        ))}
      </ul>

      <p className="mt-4 border-t border-[var(--border)] pt-3 text-[11px] leading-normal text-[var(--fg-muted)]">
        {insights.promotions_7d} promotions · {insights.episodics_created_7d} episodic memories
        created (7d)
      </p>
    </section>
  );
}
