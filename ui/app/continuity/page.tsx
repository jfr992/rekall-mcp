"use client";

import { SerifHeading } from "@/components/ui/serif-heading";
import { Skeleton } from "@/components/ui/skeleton";
import { Empty } from "@/components/ui/empty";
import { ResumeHeader } from "@/components/continuity/resume-header";
import { ImportantSection } from "@/components/continuity/important-section";
import { RecentSection } from "@/components/continuity/recent-section";
import { NextStepsList } from "@/components/continuity/next-steps-list";
import { ConflictsPanel } from "@/components/continuity/conflicts-panel";
import { TruncatedWarning } from "@/components/continuity/truncated-warning";
import { useResume } from "@/lib/queries/use-resume";
import { useProjectStore } from "@/lib/project-store";

export default function ContinuityPage() {
  const project = useProjectStore((s) => s.project);
  const { data, isLoading, isError } = useResume(project);

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <SerifHeading eyebrow="WHAT TO LOAD ON SESSION START" title={`Continuity · ${project}`} />

      {isLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-24 w-full" />
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <Skeleton className="h-64 w-full" />
            <Skeleton className="h-64 w-full" />
            <Skeleton className="h-64 w-full" />
          </div>
        </div>
      ) : isError || !data ? (
        <Empty title="Could not load continuity" hint="Check backend connection" />
      ) : (
        <>
          <TruncatedWarning truncated={data.truncated} />
          <ResumeHeader scope={data.scope} />
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
            <ImportantSection items={data.important} />
            <RecentSection items={data.recent} />
            <ConflictsPanel conflicts={data.unresolved} />
          </div>
          <NextStepsList steps={data.next_steps} />
        </>
      )}
    </div>
  );
}
