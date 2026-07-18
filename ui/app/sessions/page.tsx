"use client";

import { useState } from "react";
import { SerifHeading } from "@/components/ui/serif-heading";
import { Skeleton } from "@/components/ui/skeleton";
import { Empty } from "@/components/ui/empty";
import { Chip } from "@/components/ui/chip";
import { SessionList } from "@/components/sessions/session-list";
import { SessionDetail } from "@/components/sessions/session-detail";
import { MemoryInspector } from "@/components/memory-inspector/memory-inspector";
import { useSessions, useSessionDetail } from "@/lib/queries/use-sessions";
import { useMemoryDetail } from "@/lib/queries/use-memory-detail";
import { useProjectStore } from "@/lib/project-store";
import type { SessionsRange } from "@/lib/api/sessions";

const DAY_MS = 86_400_000;

function day(offsetDays: number): string {
  return new Date(Date.now() - offsetDays * DAY_MS).toISOString().slice(0, 10);
}

const RANGE_OPTIONS = ["Today", "Yesterday", "7d", "30d", "All"] as const;
type RangeKey = (typeof RANGE_OPTIONS)[number];

function rangeFor(key: RangeKey): SessionsRange {
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

export default function SessionsPage() {
  const project = useProjectStore((s) => s.project);
  // The fold is event-count windowed, not day-windowed — the honest default
  // is All (unbounded), matching the pre-range behavior.
  const [rangeKey, setRangeKey] = useState<RangeKey | null>("All");
  const [jumpDay, setJumpDay] = useState<string | null>(null);
  const range = jumpDay ? { after: jumpDay, before: jumpDay } : rangeFor(rangeKey ?? "All");
  const { data, isLoading, isError } = useSessions(project, 50, range);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedMemoryId, setSelectedMemoryId] = useState<string | null>(null);
  const detail = useSessionDetail(selectedId);
  const memoryDetail = useMemoryDetail(selectedMemoryId);

  const oldestDay = data?.event_window.oldest_at?.slice(0, 10) ?? null;
  const truncated =
    oldestDay !== null && (range.after === undefined || range.after < oldestDay);

  return (
    <div className="mx-auto flex h-[calc(100vh-3.5rem)] max-w-7xl flex-col gap-6 p-6">
      <SerifHeading eyebrow="RECALL TRANSPARENCY · LIVE" title="Sessions" />

      <div
        role="group"
        aria-label="Sessions range"
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
          sessions before {oldestDay} not shown (event log window)
        </p>
      ) : null}

      {isLoading ? (
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[minmax(300px,2fr)_3fr]">
          <Skeleton className="h-full w-full" />
          <Skeleton className="h-full w-full" />
        </div>
      ) : isError || !data ? (
        <Empty title="Could not load sessions" hint="Check backend connection" />
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[minmax(300px,2fr)_3fr]">
          <SessionList
            sessions={data.sessions}
            selectedId={selectedId}
            onSelect={setSelectedId}
            emptyMessage={
              range.after || range.before ? "No sessions in this range" : undefined
            }
          />
          {selectedId === null ? (
            <Empty
              title="Select a session"
              hint="Injected memories and recall cards show here"
            />
          ) : detail.isLoading ? (
            <Skeleton className="h-full w-full" />
          ) : detail.isError || !detail.data ? (
            <Empty title="Could not load session" hint="Check backend connection" />
          ) : (
            <SessionDetail session={detail.data} onExpandMemory={setSelectedMemoryId} />
          )}
        </div>
      )}

      <MemoryInspector
        open={selectedMemoryId !== null}
        detail={memoryDetail.data}
        isLoading={memoryDetail.isLoading}
        currentProject=""
        onClose={() => setSelectedMemoryId(null)}
        onSelectMemory={setSelectedMemoryId}
      />
    </div>
  );
}
