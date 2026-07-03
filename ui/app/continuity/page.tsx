"use client";

import { useState } from "react";
import { SerifHeading } from "@/components/ui/serif-heading";
import { Skeleton } from "@/components/ui/skeleton";
import { Empty } from "@/components/ui/empty";
import { ResumeHeader } from "@/components/continuity/resume-header";
import { SectionGroup } from "@/components/continuity/section-group";
import { ImportantSection } from "@/components/continuity/important-section";
import { RecentSection } from "@/components/continuity/recent-section";
import { NextStepsList } from "@/components/continuity/next-steps-list";
import { ConflictsPanel } from "@/components/continuity/conflicts-panel";
import { TruncatedWarning } from "@/components/continuity/truncated-warning";
import { MemoryInspector } from "@/components/memory-inspector/memory-inspector";
import { useResume } from "@/lib/queries/use-resume";
import { useMemoryDetail } from "@/lib/queries/use-memory-detail";
import { useProjectStore } from "@/lib/project-store";

export default function ContinuityPage() {
  const project = useProjectStore((s) => s.project);
  const { data, isLoading, isError } = useResume(project);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const detail = useMemoryDetail(selectedId, project || undefined);

  // Empty string is the all-scope sentinel; render human-readable label in heading
  const headingProject = project || "all memories";

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-6">
      <SerifHeading eyebrow="WHAT TO LOAD ON SESSION START" title={`Continuity · ${headingProject}`} />

      {isLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
        </div>
      ) : isError || !data ? (
        <Empty title="Could not load continuity" hint="Check backend connection" />
      ) : (
        <>
          <TruncatedWarning truncated={data.truncated} />
          <ResumeHeader scope={data.scope} />

          <SectionGroup
            title="Important"
            eyebrow="HIGH-SIGNAL MEMORIES"
            count={data.important.length}
            defaultOpen
          >
            <ImportantSection items={data.important} onSelect={setSelectedId} />
          </SectionGroup>

          <SectionGroup
            title="Unresolved"
            eyebrow="CONTRADICTIONS"
            count={data.unresolved.length}
            defaultOpen={data.unresolved.length > 0}
          >
            <ConflictsPanel conflicts={data.unresolved} onSelect={setSelectedId} />
          </SectionGroup>

          <SectionGroup title="Recent" eyebrow="MOST RECENT BY DATE" count={data.recent.length}>
            <RecentSection items={data.recent} onSelect={setSelectedId} />
          </SectionGroup>

          <SectionGroup title="Next Steps" eyebrow="WHAT TO DO NEXT" count={data.next_steps.length}>
            <NextStepsList steps={data.next_steps} />
          </SectionGroup>

          <MemoryInspector
            open={selectedId !== null}
            detail={detail.data}
            isLoading={detail.isLoading}
            currentProject={project}
            onClose={() => setSelectedId(null)}
            onSelectMemory={setSelectedId}
          />
        </>
      )}
    </div>
  );
}
