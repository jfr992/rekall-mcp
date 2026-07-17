"use client";

import { useRef, useMemo, useCallback, useEffect, useLayoutEffect, useState } from "react";
import dynamic from "next/dynamic";
import { typeColor, tierColor } from "@/lib/theme";
import { buildNodeTooltip } from "./tooltip";
import type { GraphNode, GraphLink } from "@/lib/schemas";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
}) as unknown as React.ComponentType<Record<string, unknown>>;

type Props = {
  nodes: GraphNode[];
  links: GraphLink[];
  selectedId?: string | null;
  onNodeClick: (memoryId: string) => void;
  particles?: boolean; // panel mode passes false — no directional particles
};

type EnrichedNode = GraphNode & {
  __color: string;
  __radius: number;
  __phase: number;
  fx: number; // pinned PCA position — layout is the projection, no drift
  fy: number;
};

// Slow global clock for breathing
let _t = 0;
if (typeof window !== "undefined") {
  const tick = () => { _t += 0.008; requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
}

export function BrainCanvas({ nodes, links, selectedId, onNodeClick, particles = true }: Props) {
  const fgRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  // null until first measure — the graph only mounts with real container dims
  const [dimensions, setDimensions] = useState<{ width: number; height: number } | null>(null);

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => {
      const { width, height } = el.getBoundingClientRect();
      if (width > 0 && height > 0) {
        setDimensions((d) => (d && d.width === width && d.height === height ? d : { width, height }));
      } else {
        // Unmeasurable container (jsdom) — fall back so the graph still mounts
        setDimensions((d) => d ?? { width: 900, height: 650 });
      }
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Map backend PCA positions (unit disc) to the viewport with padding.
  // Uniform scale (no per-axis stretch) keeps the disc a disc, not a box.
  const enriched = useMemo<EnrichedNode[]>(() => {
    if (!dimensions) return [];
    // Proportional padding — a fixed 100px pad ate most of a small panel
    const padX = Math.max(24, dimensions.width * 0.1);
    const padY = Math.max(24, dimensions.height * 0.1);
    const w = dimensions.width - padX * 2;
    const h = dimensions.height - padY * 2;
    const scale = Math.min(w, h) / 2;

    // Collect raw positions and compute centroid for re-centering
    const rawPositions = nodes.map((n) => {
      const pos = (n as any).position;
      return {
        x: pos?.x ?? (Math.random() * 2 - 1),
        y: pos?.y ?? (Math.random() * 2 - 1),
      };
    });

    const cx = rawPositions.length > 0
      ? rawPositions.reduce((s, p) => s + p.x, 0) / rawPositions.length : 0;
    const cy = rawPositions.length > 0
      ? rawPositions.reduce((s, p) => s + p.y, 0) / rawPositions.length : 0;

    return nodes.map((n, i) => {
      // INITIAL positions from backend, re-centered — d3 will refine from here
      const centered = {
        x: rawPositions[i].x - cx,
        y: rawPositions[i].y - cy,
      };

      // Use TIER for primary color (more balanced than type which is 88% learning)
      const tier = n.tier ?? "working";
      const color = tier === "working" ? typeColor(n.type) : tierColor(tier);

      const durability = n.durability ?? 0;
      const degree = n.degree ?? 0;
      const radius = Math.max(4, 3 + Math.sqrt(degree + 1) * 1.8 + durability * 4);

      return {
        ...n,
        __color: color,
        __radius: radius,
        __phase: i * 0.7,
        fx: centered.x * scale,
        fy: centered.y * scale,
      };
    });
  }, [nodes, dimensions]);

  const hoverNeighbors = useMemo(() => {
    if (!hoveredId) return null;
    const s = new Set<string>([hoveredId]);
    for (const l of links) {
      const src = typeof l.source === "object" ? (l.source as any)?.id : l.source;
      const tgt = typeof l.target === "object" ? (l.target as any)?.id : l.target;
      if (src === hoveredId) s.add(String(tgt));
      if (tgt === hoveredId) s.add(String(src));
    }
    return s;
  }, [hoveredId, links]);

  // Fit viewport to the pinned layout after data loads
  useEffect(() => {
    if (enriched.length > 0 && fgRef.current) {
      const t = setTimeout(() => {
        try {
          fgRef.current?.zoomToFit?.(400, 80);
        } catch {}
      }, 300);
      return () => clearTimeout(t);
    }
    // dimensions: refit when the panel is resized, not just on data load
  }, [enriched.length, dimensions]);

  // ---------- NODE RENDERING ----------
  const nodeCanvasObject = useCallback(
    (node: any, ctx: CanvasRenderingContext2D) => {
      const x: number = node.x ?? node.fx;
      const y: number = node.y ?? node.fy;
      if (!Number.isFinite(x) || !Number.isFinite(y)) return;

      const baseR: number = node.__radius;
      const color: string = node.__color ?? "#a0aec0";
      const phase: number = node.__phase ?? 0;
      const isSelected = node.id === selectedId;
      const isHovered = node.id === hoveredId;
      const isDimmed = hoverNeighbors !== null && !hoverNeighbors.has(node.id);

      const breath = Math.sin(_t + phase) * 0.06;
      const r = baseR * (1 + breath);

      ctx.save();

      if (isDimmed) {
        ctx.globalAlpha = 0.1;
      }

      // Halo — smaller at high node counts to prevent blob merge
      if (!isDimmed) {
        const haloR = r * 2;
        const halo = ctx.createRadialGradient(x, y, r * 0.3, x, y, haloR);
        halo.addColorStop(0, color + "18");
        halo.addColorStop(0.6, color + "08");
        halo.addColorStop(1, color + "00");
        ctx.beginPath();
        ctx.arc(x, y, haloR, 0, Math.PI * 2);
        ctx.fillStyle = halo;
        ctx.fill();
      }

      // Membrane
      ctx.beginPath();
      ctx.arc(x, y, r * 1.25, 0, Math.PI * 2);
      ctx.fillStyle = color + "15";
      ctx.fill();

      // Body
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.globalAlpha = isDimmed ? 0.1 : 0.88;
      ctx.fill();
      ctx.globalAlpha = isDimmed ? 0.1 : 1;

      // Nucleus
      if (r > 3 && !isDimmed) {
        const nr = r * 0.3;
        const nuc = ctx.createRadialGradient(x, y, 0, x, y, nr);
        nuc.addColorStop(0, "#ffffffcc");
        nuc.addColorStop(0.5, color);
        nuc.addColorStop(1, color + "00");
        ctx.beginPath();
        ctx.arc(x, y, nr, 0, Math.PI * 2);
        ctx.fillStyle = nuc;
        ctx.globalAlpha = 0.6 + breath;
        ctx.fill();
        ctx.globalAlpha = 1;
      }

      // Tier ring
      const tier = node.tier;
      if (tier && tier !== "working" && !isDimmed) {
        ctx.beginPath();
        ctx.arc(x, y, r + 2.5, 0, Math.PI * 2);
        ctx.strokeStyle = tierColor(tier);
        ctx.lineWidth = tier === "identity" ? 2.5 : 1;
        ctx.globalAlpha = tier === "identity" ? 0.9 : 0.45;
        ctx.stroke();
        ctx.globalAlpha = 1;
      }

      // Selection ring
      if (isSelected) {
        ctx.beginPath();
        ctx.arc(x, y, r + 5, 0, Math.PI * 2);
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // Hover ring
      if (isHovered && !isSelected) {
        ctx.beginPath();
        ctx.arc(x, y, r + 4, 0, Math.PI * 2);
        ctx.strokeStyle = "rgba(255,255,255,0.3)";
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      ctx.restore();
    },
    [selectedId, hoveredId, hoverNeighbors]
  );

  // ---------- LINK RENDERING ----------
  const linkCanvasObject = useCallback(
    (link: any, ctx: CanvasRenderingContext2D) => {
      const src = link.source;
      const tgt = link.target;
      if (!src || !tgt || !Number.isFinite(src.x) || !Number.isFinite(tgt.x)) return;

      const relation = link.relation ?? "related_to";
      const weight = Math.min(1, link.weight ?? 0.3);
      const isDimmed =
        hoverNeighbors !== null &&
        !(hoverNeighbors.has(src.id) && hoverNeighbors.has(tgt.id));

      ctx.save();
      const alpha = isDimmed ? 0.005 : Math.max(0.02, weight * 0.15);

      ctx.beginPath();
      ctx.moveTo(src.x, src.y);
      ctx.lineTo(tgt.x, tgt.y);

      if (relation === "contradicts") {
        ctx.strokeStyle = `rgba(245, 101, 101, ${isDimmed ? 0.005 : 0.15})`;
        ctx.lineWidth = 0.8;
        ctx.setLineDash([4, 4]);
      } else {
        ctx.strokeStyle = `rgba(160, 175, 210, ${alpha})`;
        ctx.lineWidth = 0.3 + weight * 0.5;
      }
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();
    },
    [hoverNeighbors]
  );

  // ---------- TOOLTIP ----------
  const nodeLabel = useCallback((node: any) => buildNodeTooltip(node), []);

  return (
    <div ref={containerRef} className="h-full w-full">
      {dimensions === null ? null : (
      <ForceGraph2D
        ref={fgRef}
        graphData={{ nodes: enriched as object[], links: links as object[] }}
        width={dimensions.width}
        height={dimensions.height}
        backgroundColor="rgba(0,0,0,0)"
        // PCA positions are the layout — pinned, no simulation drift
        warmupTicks={0}
        cooldownTicks={0}
        // Node
        nodeCanvasObject={nodeCanvasObject}
        nodePointerAreaPaint={(node: any, color: string, ctx: CanvasRenderingContext2D) => {
          const px: number = node.x ?? node.fx;
          const py: number = node.y ?? node.fy;
          if (!Number.isFinite(px) || !Number.isFinite(py)) return;
          ctx.beginPath();
          ctx.arc(px, py, (node.__radius ?? 5) + 8, 0, Math.PI * 2);
          ctx.fillStyle = color;
          ctx.fill();
        }}
        // Link
        linkCanvasObject={linkCanvasObject}
        linkDirectionalParticles={particles ? 1 : 0}
        linkDirectionalParticleWidth={1.2}
        linkDirectionalParticleColor={() => "rgba(160, 175, 210, 0.35)"}
        linkDirectionalParticleSpeed={0.002}
        // Hover
        nodeLabel={nodeLabel}
        onNodeHover={(node: any) => setHoveredId(node?.id ?? null)}
        // Click
        onNodeClick={(node: any) => {
          if (node?.id) onNodeClick(String(node.id));
        }}
        minZoom={0.3}
        maxZoom={8}
      />
      )}
    </div>
  );
}
