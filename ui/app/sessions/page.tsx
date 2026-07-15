"use client";

import { useState } from "react";
import { SerifHeading } from "@/components/ui/serif-heading";
import { Skeleton } from "@/components/ui/skeleton";
import { Empty } from "@/components/ui/empty";
import { SessionList } from "@/components/sessions/session-list";
import { SessionDetail } from "@/components/sessions/session-detail";
import { MemoryInspector } from "@/components/memory-inspector/memory-inspector";
import { useSessions, useSessionDetail } from "@/lib/queries/use-sessions";
import { useMemoryDetail } from "@/lib/queries/use-memory-detail";

export default function SessionsPage() {
  const { data, isLoading, isError } = useSessions();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedMemoryId, setSelectedMemoryId] = useState<string | null>(null);
  const detail = useSessionDetail(selectedId);
  const memoryDetail = useMemoryDetail(selectedMemoryId);

  return (
    <div className="mx-auto flex h-[calc(100vh-3.5rem)] max-w-7xl flex-col gap-6 p-6">
      <SerifHeading eyebrow="RECALL TRANSPARENCY · LIVE" title="Sessions" />

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
