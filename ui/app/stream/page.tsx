"use client";

import { useState } from "react";
import { ConsolidationLadder } from "@/components/stream/consolidation-ladder";
import { Timeline } from "@/components/stream/timeline";
import { Chip } from "@/components/ui/chip";
import { Empty } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { useInsights } from "@/lib/queries/use-insights";
import { usePressure } from "@/lib/queries/use-pressure";
import { useStream } from "@/lib/queries/use-stream";
import { useProjectStore } from "@/lib/project-store";
import type { StreamRange } from "@/lib/api/stream";

const DAY_MS = 86_400_000;

function day(offsetDays: number): string {
  return new Date(Date.now() - offsetDays * DAY_MS).toISOString().slice(0, 10);
}

const RANGE_OPTIONS = ["Today", "Yesterday", "7d", "30d", "All"] as const;
type RangeKey = (typeof RANGE_OPTIONS)[number];

function rangeFor(key: RangeKey): StreamRange {
  switch (key) {
    case "Today":
      return { after: day(0), before: day(0) };
    case "Yesterday":
      return { after: day(1), before: day(1) };
    case "7d":
      return { after: day(7) };
    case "30d":
      return { after: day(30) };
    case "All":
      return {};
  }
}

export default function StreamPage() {
  const project = useProjectStore((s) => s.project);
  // Datadog-lite range row — a jumped-to day overrides the chip selection.
  const [rangeKey, setRangeKey] = useState<RangeKey | null>("7d");
  const [jumpDay, setJumpDay] = useState<string | null>(null);
  const range = jumpDay ? { after: jumpDay, before: jumpDay } : rangeFor(rangeKey ?? "All");

  const stream = useStream(project, 50, range);
  const insights = useInsights(project);
  const pressure = usePressure(project);

  const oldestDay = stream.data?.event_window.oldest_at?.slice(0, 10) ?? null;
  const truncated =
    oldestDay !== null && (range.after === undefined || range.after < oldestDay);

  return (
    <div className="mx-auto grid max-w-7xl grid-cols-1 gap-6 p-6 lg:grid-cols-[240px_1fr]">
      {insights.isLoading ? (
        <Skeleton className="h-[420px] w-full" />
      ) : insights.data ? (
        <ConsolidationLadder
          tierCounts={insights.data.tier_counts}
          promotions7d={insights.data.promotions_7d}
          staleWorkingCount={pressure.data?.flagged.stale_working_count ?? null}
        />
      ) : (
        <Empty title="Could not load insights" hint="Check backend connection" />
      )}
      <div className="flex min-w-0 flex-col gap-4">
        <div
          role="group"
          aria-label="Stream range"
          className="flex flex-wrap items-center gap-1.5"
        >
          {RANGE_OPTIONS.map((key) => (
            <Chip
              key={key}
              active={rangeKey === key}
              onClick={() => {
                setRangeKey(key);
                setJumpDay(null);
              }}
            >
              {key}
            </Chip>
          ))}
          <input
            type="date"
            aria-label="Jump to day"
            value={jumpDay ?? ""}
            onChange={(e) => {
              if (e.target.value) {
                setJumpDay(e.target.value);
                setRangeKey(null);
              }
            }}
            className="ml-2 rounded border border-[var(--border)] bg-transparent px-1.5 py-0.5 font-mono text-xs text-[var(--fg-muted)] [color-scheme:dark]"
          />
        </div>
        {truncated ? (
          <p className="font-mono text-[10px] text-[var(--fg-dim)]">
            recalls/promotions before {oldestDay} not shown (event log window)
          </p>
        ) : null}
        {stream.isLoading ? (
          <Skeleton className="h-[420px] w-full" />
        ) : stream.isError || !stream.data ? (
          <Empty title="Could not load stream" hint="Check backend connection" />
        ) : (
          <Timeline rows={stream.data.rows} />
        )}
      </div>
    </div>
  );
}
