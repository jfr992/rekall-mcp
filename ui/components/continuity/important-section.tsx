"use client";

import { MonoLabel } from "@/components/ui/mono-label";
import { Empty } from "@/components/ui/empty";
import { MemoryRow } from "@/components/continuity/memory-row";

type ImportantItem = {
  memory_id: string;
  content: string;
  type?: string;
  tier?: string;
  date?: string;
  importance?: number;
};

// Importance order — musts first, ambient context last
const TYPE_ORDER = [
  "requirement",
  "decision",
  "preference",
  "learning",
  "fact",
  "note",
  "session",
  "summary",
];

export function ImportantSection({
  items,
  onSelect,
}: {
  items: ImportantItem[];
  onSelect: (memoryId: string) => void;
}) {
  if (items.length === 0) {
    return <Empty title="Nothing important yet" />;
  }

  const byType = new Map<string, ImportantItem[]>();
  for (const item of items) {
    const t = item.type ?? "note";
    const bucket = byType.get(t) ?? [];
    bucket.push(item);
    byType.set(t, bucket);
  }

  const orderedTypes = [
    ...TYPE_ORDER.filter((t) => byType.has(t)),
    ...[...byType.keys()].filter((t) => !TYPE_ORDER.includes(t)),
  ];

  return (
    <div className="space-y-4">
      {orderedTypes.map((type) => (
        <section key={type}>
          <MonoLabel>
            {type} · {byType.get(type)!.length}
          </MonoLabel>
          <ul className="mt-2 space-y-1.5">
            {byType.get(type)!.map((item) => (
              <li key={item.memory_id}>
                <MemoryRow
                  memoryId={item.memory_id}
                  content={item.content}
                  type={item.type}
                  tier={item.tier}
                  date={item.date}
                  onSelect={onSelect}
                />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
