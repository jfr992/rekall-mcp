"use client";

import { useState } from "react";
import { BrainScene } from "@/components/brain/brain-scene";
import { BrainCanvas } from "@/components/brain/brain-canvas";
import { NodeDrawer } from "@/components/brain/node-drawer";
import { TypeLegend } from "@/components/brain/type-legend";
import { TierLegend } from "@/components/brain/tier-legend";
import { GraphStats } from "@/components/brain/graph-stats";
import { Empty } from "@/components/ui/empty";
import { useBrainGraph } from "@/lib/queries/use-brain-graph";
import { useMemoryDetail } from "@/lib/queries/use-memory-detail";
import { useProjectStore } from "@/lib/project-store";
import type { GraphNode, GraphLink } from "@/lib/schemas";

export default function BrainPage() {
  const project = useProjectStore((s) => s.project);
  const { data, dataUpdatedAt, isLoading } = useBrainGraph(project);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const detail = useMemoryDetail(selectedId);

  const nodes = (data?.graph?.nodes ?? []) as GraphNode[];
  const links = (data?.graph?.links ?? []) as GraphLink[];
  const refreshedAt = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString()
    : "…";

  return (
    <div className="relative h-[calc(100vh-3.5rem)] w-full">
      <BrainScene>
        {nodes.length === 0 && !isLoading ? (
          <div className="flex h-full items-center justify-center">
            <Empty
              title="No memories in this project yet"
              hint="Try observe() from your agent"
            />
          </div>
        ) : (
          <BrainCanvas
            nodes={nodes}
            links={links}
            selectedId={selectedId}
            onNodeClick={setSelectedId}
          />
        )}
      </BrainScene>

      <div className="pointer-events-none absolute right-6 top-6 flex justify-end">
        <div className="pointer-events-auto">
          <GraphStats
            nodeCount={nodes.length}
            linkCount={links.length}
            refreshedAt={refreshedAt}
          />
        </div>
      </div>

      <div className="pointer-events-none absolute bottom-6 left-6 flex flex-col gap-2">
        <div className="pointer-events-auto">
          <TypeLegend />
        </div>
        <div className="pointer-events-auto">
          <TierLegend />
        </div>
      </div>

      <NodeDrawer
        open={selectedId !== null}
        detail={detail.data}
        isLoading={detail.isLoading}
        onClose={() => setSelectedId(null)}
      />
    </div>
  );
}
