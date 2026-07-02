"use client";

import { Empty } from "@/components/ui/empty";
import { MemoryRow } from "@/components/continuity/memory-row";

type RecentItem = {
  memory_id: string;
  content: string;
  date?: string;
  type?: string;
  tier?: string;
};

export function RecentSection({
  items,
  onSelect,
}: {
  items: RecentItem[];
  onSelect: (memoryId: string) => void;
}) {
  if (items.length === 0) {
    return <Empty title="No recent activity" />;
  }
  return (
    <ul className="space-y-1.5">
      {items.map((item) => (
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
  );
}
