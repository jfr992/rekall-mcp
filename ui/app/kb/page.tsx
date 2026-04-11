"use client";

import { KbColumns } from "@/components/kb/kb-columns";
import { SerifHeading } from "@/components/ui/serif-heading";
import { Empty } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { useKb } from "@/lib/queries/use-kb";
import { useProjectStore } from "@/lib/project-store";

export default function KbPage() {
  const project = useProjectStore((s) => s.project);
  const { data, isLoading, isError } = useKb(project);

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <SerifHeading eyebrow="CURATED BY TYPE · LIVE" title={`Knowledge Base · ${project}`} />
      {isLoading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-96 w-full" />
          ))}
        </div>
      ) : isError || !data ? (
        <Empty title="Could not load knowledge base" hint="Check backend connection" />
      ) : (
        <KbColumns data={data} />
      )}
    </div>
  );
}
