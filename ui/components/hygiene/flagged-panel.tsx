"use client";

import { MonoLabel } from "@/components/ui/mono-label";
import { MemoryRow } from "@/components/continuity/memory-row";

type FlaggedMemory = {
  memory_id: string;
  content: string;
  type?: string | null;
  tier?: string | null;
  date?: string | null;
};

type Props = {
  flagged: {
    stale_working: FlaggedMemory[];
    low_value: FlaggedMemory[];
    conflict: FlaggedMemory[];
  };
  onSelect: (memoryId: string) => void;
};

const GROUPS: Array<[keyof Props["flagged"], string, string]> = [
  ["conflict", "Conflicts", "carry a contradicts edge — see the resolution playbook in TUNING"],
  ["stale_working", "Stale", "working-tier past their retention window"],
  ["low_value", "Low value", "working-tier with low salience"],
];

export function FlaggedPanel({ flagged, onSelect }: Props) {
  const total = GROUPS.reduce((n, [key]) => n + flagged[key].length, 0);
  if (total === 0) return null;
  return (
    <div className="space-y-3.5">
      {GROUPS.map(([key, title, hint]) =>
        flagged[key].length === 0 ? null : (
          <section
            key={key}
            className="rounded-[11px] border border-[var(--border)] bg-[var(--bg-elevated)] px-5 py-4"
          >
            <MonoLabel className="tracking-[0.16em]">
              {title} · {flagged[key].length} — {hint}
            </MonoLabel>
            <ul className="mt-3 space-y-1.5">
              {flagged[key].map((m) => (
                <li key={`${key}-${m.memory_id}`}>
                  <MemoryRow
                    memoryId={m.memory_id}
                    content={m.content}
                    type={m.type ?? undefined}
                    tier={m.tier ?? undefined}
                    date={m.date ?? undefined}
                    onSelect={onSelect}
                  />
                </li>
              ))}
            </ul>
          </section>
        )
      )}
    </div>
  );
}
