"use client";

import { useMemo, useState } from "react";
import { BrainScene } from "@/components/brain/brain-scene";
import { BrainCanvas } from "@/components/brain/brain-canvas";
import { BrainNodeList } from "@/components/brain/brain-node-list";
import { TypeLegend } from "@/components/brain/type-legend";
import { TierLegend } from "@/components/brain/tier-legend";
import { GraphStats } from "@/components/brain/graph-stats";
import { MemoryInspector } from "@/components/memory-inspector/memory-inspector";
import { Empty } from "@/components/ui/empty";
import { useBrainGraph } from "@/lib/queries/use-brain-graph";
import { useMemoryDetail } from "@/lib/queries/use-memory-detail";
import { useProjectStore } from "@/lib/project-store";
import type { GraphNode, GraphLink } from "@/lib/schemas";

export default function BrainPage() {
  const project = useProjectStore((s) => s.project);
  const { data, dataUpdatedAt, isLoading } = useBrainGraph(project);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const detail = useMemoryDetail(selectedId, project || undefined);

  const nodes = (data?.graph?.nodes ?? []) as GraphNode[];
  const rawLinks = (data?.graph?.links ?? []) as GraphLink[];

  // Sparsify links — at scale (100+ nodes), showing every edge creates a hairball.
  // Keep only the strongest connections: top N per node + all contradicts.
  const links = useMemo(() => {
    if (rawLinks.length < 300) return rawLinks; // small graphs are fine

    const MAX_LINKS_PER_NODE = 2;
    const kept = new Set<number>();

    // Contradicts edges only show on hover — skip them in the default view

    // For each node, keep top N strongest links by weight
    const nodeIds = new Set(nodes.map((n) => n.id));
    for (const nid of nodeIds) {
      const nodeLinks = rawLinks
        .map((l, i) => ({ l, i }))
        .filter(({ l }) => {
          const src = typeof l.source === "object" ? (l.source as any)?.id : l.source;
          const tgt = typeof l.target === "object" ? (l.target as any)?.id : l.target;
          return src === nid || tgt === nid;
        })
        .sort((a, b) => (b.l.weight ?? 0) - (a.l.weight ?? 0));

      for (let j = 0; j < Math.min(MAX_LINKS_PER_NODE, nodeLinks.length); j++) {
        kept.add(nodeLinks[j].i);
      }
    }

    return rawLinks.filter((_, i) => kept.has(i));
  }, [rawLinks, nodes]);

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

      {/* Keyboard-accessible fallback — lets users select nodes without canvas pointer */}
      <div className="pointer-events-none absolute bottom-6 right-6 flex flex-col items-end gap-2">
        <div className="pointer-events-auto">
          <BrainNodeList
            nodes={nodes}
            selectedId={selectedId}
            onSelect={setSelectedId}
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

      <MemoryInspector
        open={selectedId !== null}
        detail={detail.data}
        isLoading={detail.isLoading}
        currentProject={project}
        onClose={() => setSelectedId(null)}
        onSelectMemory={setSelectedId}
      />
    </div>
  );
}
