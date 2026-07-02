"use client";

import { AlertTriangle } from "lucide-react";
import { MonoLabel } from "@/components/ui/mono-label";

type Conflict = { memory_id: string; conflicts_with: string; content?: string };

export function ConflictsPanel({
  conflicts,
  onSelect,
}: {
  conflicts: Conflict[];
  onSelect: (memoryId: string) => void;
}) {
  if (conflicts.length === 0) {
    return (
      <div className="rounded-md border border-[var(--accent-success)]/30 bg-[var(--accent-success)]/10 p-4 font-serif text-sm text-[var(--fg)]">
        All clear.
      </div>
    );
  }
  return (
    <ul className="space-y-1.5">
      {conflicts.map((c, i) => (
        <li key={`${c.memory_id}-${i}`}>
          <button
            type="button"
            onClick={() => onSelect(c.memory_id)}
            className="flex w-full items-start gap-3 rounded-md border border-[var(--accent-danger)]/40 bg-[var(--accent-danger)]/10 p-3 text-left transition-colors hover:border-[var(--accent-danger)]/70"
          >
            <AlertTriangle size={14} className="mt-0.5 shrink-0 text-[var(--accent-danger)]" />
            <div className="min-w-0 flex-1">
              <MonoLabel>
                {c.memory_id} ↔ {c.conflicts_with}
              </MonoLabel>
              {c.content ? (
                <p className="mt-1 truncate text-xs text-[var(--fg-muted)]">{c.content}</p>
              ) : null}
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}
