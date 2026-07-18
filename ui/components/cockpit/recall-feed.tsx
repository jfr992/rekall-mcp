"use client";

import { MonoLabel } from "@/components/ui/mono-label";
import { ShowMoreList } from "@/components/ui/show-more-list";
import { recallOriginLabel } from "@/lib/recall-origin";
import type { StreamRow } from "@/lib/schemas";

const FEED_CAP = 8;

type RecalledRow = Extract<StreamRow, { kind: "recalled" }>;

type Props = {
  rows: StreamRow[];
  misses7d: number;
  onSelect: (memoryId: string) => void;
  scoped?: boolean;
};

function hhmm(at: string): string {
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return "--:--";
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function RecallFeed({ rows, misses7d, onSelect, scoped = false }: Props) {
  const recalled = rows.filter((r): r is RecalledRow => r.kind === "recalled");

  return (
    <section className="flex flex-col rounded-[11px] border border-[var(--border)] bg-[var(--bg-elevated)] px-5 py-4">
      <MonoLabel className="mb-3.5 block text-[9px] tracking-[0.16em]">Live recall feed</MonoLabel>

      <div className="flex flex-1 flex-col gap-0.5 text-xs">
        {recalled.length === 0 && scoped ? (
          <p className="py-6 text-center text-[11px] text-[var(--fg-muted)]">
            No recalls in this scope yet — recalls attribute to a project when the agent passes
            its working directory
          </p>
        ) : null}
        <ShowMoreList
          items={recalled}
          initialCount={FEED_CAP}
          viewAllHref="/stream"
          moreLabel={() => "View all in Stream →"}
          keyFor={(row, i) => `${row.at}-${i}`}
          renderItem={(row) => {
            const hits = row.payload.memory_ids.length;
            const miss = hits === 0;
            const topId = row.payload.memory_ids[0];
            // Hit rows open the inspector on their top memory; misses have none
            const Row = miss ? "div" : "button";
            return (
              <Row
                {...(miss
                  ? { "data-miss": "" }
                  : { type: "button" as const, onClick: () => onSelect(topId) })}
                className={`grid grid-cols-[52px_1fr_60px_44px] items-baseline gap-2.5 rounded-md border-0 bg-transparent px-1.5 py-2 text-left ${
                  miss
                    ? "bg-[rgba(248,113,113,0.08)]"
                    : "cursor-pointer hover:bg-[var(--surface-0)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--accent-primary)]"
                }`}
              >
                <span className="font-mono text-[10px] text-[var(--fg-dim)]">{hhmm(row.at)}</span>
                <span
                  className={`truncate ${
                    row.payload.query === null
                      ? "italic text-[var(--fg-muted)]"
                      : miss
                        ? "text-[var(--accent-danger)]"
                        : "text-[var(--fg-soft)]"
                  }`}
                >
                  {row.payload.query ?? recallOriginLabel(row.payload.capture_origin)}
                </span>
                <span className="font-mono text-[10px] text-[var(--fg-dim)]">
                  {hits} {hits === 1 ? "hit" : "hits"}
                </span>
                <span className="font-mono text-[10px] font-medium text-[var(--accent-bright)]">
                  {row.payload.top_score === null ? null : row.payload.top_score.toFixed(2)}
                </span>
              </Row>
            );
          }}
        />
      </div>

      <p className="mt-2 border-t border-[var(--border)] pt-2.5 text-[11px] text-[var(--fg-muted)]">
        {misses7d} {misses7d === 1 ? "miss" : "misses"} · 7d
      </p>
    </section>
  );
}
