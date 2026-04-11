"use client";

import { useRef, useMemo } from "react";
import { typeColor, tierColor } from "@/lib/theme";
import type { GraphNode, GraphLink } from "@/lib/schemas";

// @ts-expect-error - react-force-graph-2d types are loose
import ForceGraph2D from "react-force-graph-2d";

type Props = {
  nodes: GraphNode[];
  links: GraphLink[];
  selectedId?: string | null;
  onNodeClick: (memoryId: string) => void;
};

type GraphNodeWithVisuals = GraphNode & {
  __color: string;
  __size: number;
};

export function BrainCanvas({ nodes, links, selectedId, onNodeClick }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);

  const enriched = useMemo<GraphNodeWithVisuals[]>(
    () =>
      nodes.map((n) => ({
        ...n,
        __color: typeColor(n.type),
        __size: 4 + Math.min(n.durability ?? 0, 1) * 10,
      })),
    [nodes]
  );

  return (
    <div ref={containerRef} className="h-full w-full">
      <ForceGraph2D
        graphData={{ nodes: enriched as object[], links: links as object[] }}
        backgroundColor="rgba(0,0,0,0)"
        nodeRelSize={4}
        linkWidth={(l: any) => 0.5 + (l.weight ?? 0) * 1.5}
        linkColor={(l: any) => {
          if (l.relation === "contradicts") return "rgba(248, 113, 113, 0.6)";
          if (l.relation === "supersedes") return "rgba(96, 165, 250, 0.5)";
          return "rgba(148, 163, 184, 0.35)";
        }}
        nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D, scale: number) => {
          const r = node.__size / scale + 2;
          ctx.beginPath();
          ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
          ctx.fillStyle = node.__color ?? "#94a3b8";
          ctx.shadowColor = node.__color ?? "#94a3b8";
          ctx.shadowBlur = 14;
          ctx.fill();
          ctx.shadowBlur = 0;

          if (node.id === selectedId) {
            ctx.beginPath();
            ctx.arc(node.x, node.y, r + 4, 0, Math.PI * 2);
            ctx.strokeStyle = "#f8fafc";
            ctx.lineWidth = 1.5;
            ctx.stroke();
          }

          if (node.tier && node.tier !== "working") {
            ctx.beginPath();
            ctx.arc(node.x, node.y, r + 2, 0, Math.PI * 2);
            ctx.strokeStyle = tierColor(node.tier);
            ctx.lineWidth = 0.8;
            ctx.stroke();
          }
        }}
        onNodeClick={(node: any) => {
          if (node?.id) onNodeClick(String(node.id));
        }}
        cooldownTicks={100}
      />
    </div>
  );
}
