"use client";

import { MonoLabel } from "@/components/ui/mono-label";
import { ShowMoreList } from "@/components/ui/show-more-list";
import { MemoryRow } from "@/components/continuity/memory-row";

const VISIBLE_PER_GROUP = 5;

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
            className="max-h-[50vh] overflow-y-auto rounded-[11px] border border-[var(--border)] bg-[var(--bg-elevated)] px-5 py-4"
          >
            <MonoLabel className="sticky top-0 -mx-5 -mt-4 block bg-[var(--bg-elevated)] px-5 pb-2 pt-4 tracking-[0.16em]">
              {title} · {flagged[key].length} — {hint}
            </MonoLabel>
            <ul className="mt-3 space-y-1.5">
              <ShowMoreList
                items={flagged[key]}
                initialCount={VISIBLE_PER_GROUP}
                keyFor={(m) => `${key}-${m.memory_id}`}
                moreLabel={(_n) => `Show all ${flagged[key].length}`}
                footerWrapper={(node) => <li>{node}</li>}
                renderItem={(m: FlaggedMemory) => (
                  <li>
                    <MemoryRow
                      memoryId={m.memory_id}
                      content={m.content}
                      type={m.type ?? undefined}
                      tier={m.tier ?? undefined}
                      date={m.date ?? undefined}
                      onSelect={onSelect}
                    />
                  </li>
                )}
              />
            </ul>
          </section>
        )
      )}
    </div>
  );
}
