"use client";

import { ConsolidationLadder } from "@/components/stream/consolidation-ladder";
import { Timeline } from "@/components/stream/timeline";
import { Empty } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { useInsights } from "@/lib/queries/use-insights";
import { usePressure } from "@/lib/queries/use-pressure";
import { useStream } from "@/lib/queries/use-stream";
import { useProjectStore } from "@/lib/project-store";

export default function StreamPage() {
  const project = useProjectStore((s) => s.project);
  const stream = useStream(project);
  const insights = useInsights(project);
  const pressure = usePressure(project);

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
      {stream.isLoading ? (
        <Skeleton className="h-[420px] w-full" />
      ) : stream.isError || !stream.data ? (
        <Empty title="Could not load stream" hint="Check backend connection" />
      ) : (
        <Timeline rows={stream.data.rows} />
      )}
    </div>
  );
}
