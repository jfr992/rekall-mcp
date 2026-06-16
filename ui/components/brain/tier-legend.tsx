import { MonoLabel } from "@/components/ui/mono-label";
import { tokens } from "@/lib/theme";

const TIERS = ["identity", "semantic", "episodic", "working"] as const;

export function TierLegend() {
  return (
    <div className="flex items-center gap-3 rounded-full border border-[var(--border)] bg-[var(--bg-frost)] px-3 py-1.5 backdrop-blur-[12px]">
      <MonoLabel>tiers</MonoLabel>
      {TIERS.map((t) => (
        <span
          key={t}
          className="flex items-center gap-1 text-[11px] text-[var(--fg-muted)]"
        >
          <span
            className="h-2 w-2 rounded-full"
            style={{
              background: (tokens.tier as Record<string, string>)[t],
              boxShadow: `0 0 6px ${
                (tokens.tier as Record<string, string>)[t]
              }`,
            }}
          />
          {t}
        </span>
      ))}
    </div>
  );
}
