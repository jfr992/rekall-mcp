import { MonoLabel } from "@/components/ui/mono-label";
import { tokens } from "@/lib/theme";

const TYPES = [
  "decision",
  "requirement",
  "preference",
  "learning",
  "fact",
  "note",
] as const;

export function TypeLegend() {
  return (
    <div className="flex items-center gap-3 rounded-full border border-[var(--border)] bg-[var(--bg-frost)] px-3 py-1.5 backdrop-blur-[12px]">
      <MonoLabel>types</MonoLabel>
      {TYPES.map((t) => (
        <span
          key={t}
          className="flex items-center gap-1 text-[11px] text-[var(--fg-muted)]"
        >
          <span
            className="h-2 w-2 rounded-full"
            style={{
              background: (tokens.type as Record<string, string>)[t],
            }}
          />
          {t}
        </span>
      ))}
    </div>
  );
}
