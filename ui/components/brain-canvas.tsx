"use client";

import { useEffect, useMemo, useRef, useState } from 'react';

type BrainNode = {
  id: string;
  type?: string;
  content?: string;
  degree?: number;
};

type BrainLink = {
  source: string;
  target: string;
  weight?: number;
};

type Props = {
  nodes: BrainNode[];
  links: BrainLink[];
  pulseKey: string;
};

const COLOR_BY_TYPE: Record<string, string> = {
  requirement: '#ff6b6b',
  fact: '#5dade2',
  decision: '#f5b041',
  preference: '#af7ac5',
  learning: '#58d68d',
  session: '#cfd6e6',
  note: '#d5d8dc',
};

export function BrainCanvas({ nodes, links, pulseKey }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [selected, setSelected] = useState<BrainNode | null>(null);

  const hydratedNodes = useMemo(() => {
    return nodes.map((node, index) => {
      const angle = (index / Math.max(nodes.length, 1)) * Math.PI * 2;
      const radius = 120 + (index % 5) * 18;
      return {
        ...node,
        x: Math.cos(angle) * radius,
        y: Math.sin(angle) * radius,
      };
    });
  }, [nodes, pulseKey]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const width = canvas.width;
    const height = canvas.height;
    const cx = width / 2;
    const cy = height / 2;
    let frame = 0;
    let raf = 0;

    const draw = () => {
      frame += 1;
      ctx.clearRect(0, 0, width, height);

      const gradient = ctx.createRadialGradient(cx, cy, 20, cx, cy, 260);
      gradient.addColorStop(0, 'rgba(95, 168, 255, 0.18)');
      gradient.addColorStop(1, 'rgba(10, 16, 32, 0.04)');
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, width, height);

      const pulseRadius = 70 + Math.sin(frame / 18) * 8;
      ctx.beginPath();
      ctx.arc(cx, cy, pulseRadius, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(129, 199, 255, 0.25)';
      ctx.lineWidth = 2;
      ctx.stroke();

      for (const link of links) {
        const source = hydratedNodes.find((node) => node.id === link.source);
        const target = hydratedNodes.find((node) => node.id === link.target);
        if (!source || !target) continue;
        ctx.beginPath();
        ctx.moveTo(cx + source.x, cy + source.y);
        ctx.lineTo(cx + target.x, cy + target.y);
        ctx.strokeStyle = `rgba(143, 167, 214, ${Math.max(0.15, link.weight ?? 0.25)})`;
        ctx.lineWidth = 1 + ((link.weight ?? 0.2) * 2);
        ctx.stroke();
      }

      for (const node of hydratedNodes) {
        const radius = 5 + Math.min(10, node.degree ?? 1);
        ctx.beginPath();
        ctx.arc(cx + node.x, cy + node.y, radius, 0, Math.PI * 2);
        ctx.fillStyle = COLOR_BY_TYPE[node.type ?? 'note'] ?? '#d5d8dc';
        ctx.shadowColor = ctx.fillStyle;
        ctx.shadowBlur = 14;
        ctx.fill();
        ctx.shadowBlur = 0;

        if (selected?.id === node.id) {
          ctx.beginPath();
          ctx.arc(cx + node.x, cy + node.y, radius + 5, 0, Math.PI * 2);
          ctx.strokeStyle = '#ffffff';
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }
      }

      raf = window.requestAnimationFrame(draw);
    };

    draw();
    return () => window.cancelAnimationFrame(raf);
  }, [hydratedNodes, links, selected, pulseKey]);

  function handleClick(event: React.MouseEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left - canvas.width / 2;
    const y = event.clientY - rect.top - canvas.height / 2;

    let hit: BrainNode | null = null;
    for (const node of hydratedNodes) {
      const dx = node.x - x;
      const dy = node.y - y;
      const distance = Math.sqrt(dx * dx + dy * dy);
      if (distance < 18) {
        hit = node;
        break;
      }
    }
    setSelected(hit);
  }

  return (
    <div>
      <canvas ref={canvasRef} width={860} height={520} onClick={handleClick} style={{ width: '100%', height: 'auto', borderRadius: 18, border: '1px solid #223055' }} />
      <div style={{ marginTop: 12, fontSize: 13, color: '#9fb0d9' }}>
        {selected ? `${selected.type ?? 'memory'}: ${selected.content ?? selected.id}` : 'Click a node to inspect a memory.'}
      </div>
    </div>
  );
}
