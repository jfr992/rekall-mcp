"use client";

import { useMemo, useState } from "react";
import { BrainCanvas } from "@/components/brain/brain-canvas";
import { BrainNodeList } from "@/components/brain/brain-node-list";
import { StatCards } from "@/components/cockpit/stat-cards";
import { TierComposition } from "@/components/cockpit/tier-composition";
import { RecallFeed } from "@/components/cockpit/recall-feed";
import { HygieneQueue } from "@/components/cockpit/hygiene-queue";
import { MemoryInspector } from "@/components/memory-inspector/memory-inspector";
import { MonoLabel } from "@/components/ui/mono-label";
import { Empty } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { useInsights } from "@/lib/queries/use-insights";
import { useStream } from "@/lib/queries/use-stream";
import { usePressure } from "@/lib/queries/use-pressure";
import { useBrainGraph } from "@/lib/queries/use-brain-graph";
import { useMemoryDetail } from "@/lib/queries/use-memory-detail";
import { useProjectStore } from "@/lib/project-store";
import type { GraphNode, GraphLink } from "@/lib/schemas";

export default function BrainPage() {
  const project = useProjectStore((s) => s.project);
  const insightsQ = useInsights(project);
  // ONE stream poll per page — the feed derives from this query's cache
  const streamQ = useStream(project);
  const pressureQ = usePressure(project);
  const graphQ = useBrainGraph(project);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const detail = useMemoryDetail(selectedId, project || undefined);

  const nodes = (graphQ.data?.graph?.nodes ?? []) as GraphNode[];
  const rawLinks = (graphQ.data?.graph?.links ?? []) as GraphLink[];

  // Sparsify links — at scale (100+ nodes), showing every edge creates a hairball.
  // Keep only the strongest connections: top N per node + all contradicts.
  const links = useMemo(() => {
    if (rawLinks.length < 300) return rawLinks; // small graphs are fine

    const MAX_LINKS_PER_NODE = 2;
    const kept = new Set<number>();

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

  const insights = insightsQ.data;

  if (!insights) {
    return (
      <div className="flex flex-col gap-4 px-7 py-6">
        {insightsQ.isLoading ? (
          <>
            <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
              <Skeleton className="h-32" />
              <Skeleton className="h-32" />
              <Skeleton className="h-32" />
              <Skeleton className="h-32" />
            </div>
            <div className="grid gap-3.5 lg:grid-cols-[1fr_1.5fr_1fr]">
              <Skeleton className="h-72" />
              <Skeleton className="h-72" />
              <Skeleton className="h-72" />
            </div>
          </>
        ) : (
          <Empty
            title="Insights unavailable"
            hint="The /api/memory/insights endpoint did not respond — check the server."
          />
        )}
      </div>
    );
  }

  return (
    <div className="flex min-h-full flex-col gap-4 px-7 py-6">
      <StatCards insights={insights} pressure={pressureQ.data} />

      <div className="grid flex-1 items-start gap-3.5 lg:grid-cols-[1fr_1.5fr_1fr]">
        <TierComposition insights={insights} />

        <RecallFeed
          rows={streamQ.data?.rows ?? []}
          misses7d={insights.misses_7d}
          onSelect={setSelectedId}
          scoped={project !== ""}
        />

        <div className="flex flex-col gap-3.5">
          <div className="relative min-h-[280px] overflow-hidden rounded-[11px] border border-[var(--border-strong)] bg-[var(--bg-deep)]">
            <MonoLabel className="absolute left-4 top-3.5 z-10 text-[9px] tracking-[0.16em]">
              Neural graph
            </MonoLabel>
            {nodes.length === 0 && !graphQ.isLoading ? (
              <div className="flex h-full min-h-[280px] items-center justify-center">
                <Empty title="No memories in this project yet" hint="Try observe() from your agent" />
              </div>
            ) : (
              <div className="h-[280px]">
                <BrainCanvas
                  nodes={nodes}
                  links={links}
                  selectedId={selectedId}
                  onNodeClick={setSelectedId}
                  particles={false}
                />
              </div>
            )}
            <span className="pointer-events-none absolute bottom-2.5 left-4 font-mono text-[10px] text-[var(--fg-dim)] [text-shadow:0_1px_4px_var(--bg-deep)]">
              {nodes.length} nodes · {links.length} edges
            </span>
          </div>

          {/* Keyboard-accessible fallback — node selection without canvas pointer */}
          <BrainNodeList nodes={nodes} selectedId={selectedId} onSelect={setSelectedId} />

          <HygieneQueue pressure={pressureQ.data} />
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
