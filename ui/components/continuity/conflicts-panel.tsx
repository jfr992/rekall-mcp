import { AlertTriangle } from "lucide-react";
import { SerifHeading } from "@/components/ui/serif-heading";
import { MonoLabel } from "@/components/ui/mono-label";

type Conflict = { memory_id: string; conflicts_with: string; content?: string };

export function ConflictsPanel({ conflicts }: { conflicts: Conflict[] }) {
  return (
    <section className="space-y-3">
      <SerifHeading title="Unresolved" size="section" eyebrow="CONTRADICTIONS" />
      {conflicts.length === 0 ? (
        <div className="rounded-md border border-[var(--accent-success)]/30 bg-[var(--accent-success)]/10 p-4 font-serif text-sm text-[var(--fg)]">
          All clear.
        </div>
      ) : (
        <ul className="space-y-2">
          {conflicts.map((c, i) => (
            <li
              key={`${c.memory_id}-${i}`}
              className="flex items-start gap-3 rounded-md border border-[var(--accent-danger)]/40 bg-[var(--accent-danger)]/10 p-3"
            >
              <AlertTriangle size={14} className="mt-0.5 shrink-0 text-[var(--accent-danger)]" />
              <div className="flex-1">
                <MonoLabel>{c.memory_id} ↔ {c.conflicts_with}</MonoLabel>
                {c.content ? <p className="mt-1 text-xs text-[var(--fg-muted)]">{c.content}</p> : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
