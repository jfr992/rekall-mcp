import Link from "next/link";
import { MonoLabel } from "@/components/ui/mono-label";
import { tierColor } from "@/lib/theme";
import type { TierCounts } from "@/lib/schemas";

const TIERS = [
  { tier: "identity", tagline: "who you are · never decays" },
  { tier: "semantic", tagline: "distilled knowledge" },
  { tier: "episodic", tagline: "events & sessions" },
  { tier: "working", tagline: "volatile · decays in days" },
] as const;

type Props = {
  tierCounts: TierCounts;
  promotions7d: number;
  staleWorkingCount?: number | null;
};

export function ConsolidationLadder({ tierCounts, promotions7d, staleWorkingCount }: Props) {
  return (
    <aside className="flex flex-col gap-2" aria-label="Consolidation ladder">
      <MonoLabel className="mb-1 text-[var(--fg-dim)]">CONSOLIDATION LADDER</MonoLabel>
      {TIERS.map(({ tier, tagline }) => {
        const color = tierColor(tier);
        return (
          <div key={tier}>
            <div
              className={`rounded-lg border p-3 ${tier === "working" ? "border-dashed" : ""}`}
              style={{
                borderColor: `${color}55`,
                background: `linear-gradient(180deg, ${color}1f, ${color}08)`,
              }}
            >
              <div
                className="flex items-baseline justify-between text-sm font-medium"
                style={{ color }}
              >
                <span>{tier}</span>
                <span className="font-mono">{tierCounts[tier]}</span>
              </div>
              <div className="mt-0.5 text-[11px] text-[var(--fg-muted)]">{tagline}</div>
            </div>
            {tier === "identity" ? (
              <div className="mt-2 text-center font-mono text-[11px] text-[var(--fg-dim)]">
                ▲ {promotions7d} promoted (7d)
              </div>
            ) : null}
          </div>
        );
      })}
      <div className="mt-4 border-t border-[var(--border)] pt-3">
        <MonoLabel className="text-[var(--fg-dim)]">DECAY QUEUE</MonoLabel>
        <p className="mt-2 text-xs leading-relaxed text-[var(--fg-muted)]">
          {staleWorkingCount ?? "–"} working {staleWorkingCount === 1 ? "memory" : "memories"}{" "}
          decaying.{" "}
          <Link
            href="/hygiene"
            className="text-[var(--accent-bright)] transition-colors hover:text-[var(--fg)]"
          >
            Review →
          </Link>
        </p>
      </div>
    </aside>
  );
}
