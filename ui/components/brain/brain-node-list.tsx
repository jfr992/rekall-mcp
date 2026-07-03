"use client";

import { Badge } from "@/components/ui/badge";
import { MonoLabel } from "@/components/ui/mono-label";
import type { GraphNode } from "@/lib/schemas";

const MAX_VISIBLE = 80;

type Props = {
  nodes: GraphNode[];
  selectedId?: string | null;
  onSelect: (memoryId: string) => void;
};

export function BrainNodeList({ nodes, selectedId, onSelect }: Props) {
  const visible = nodes.slice(0, MAX_VISIBLE);

  return (
    <details className="group w-60 rounded-lg border border-[var(--border)] bg-[var(--bg-frost)] backdrop-blur-[12px]">
      <summary className="flex cursor-pointer select-none items-center justify-between gap-2 px-3 py-2 font-mono text-[11px] text-[var(--fg-muted)] hover:text-[var(--fg)]">
        <span className="uppercase tracking-[0.12em]">Nodes · {nodes.length}</span>
        <MonoLabel className="opacity-60 group-open:opacity-0">▾</MonoLabel>
      </summary>

      <div className="max-h-64 overflow-y-auto border-t border-[var(--border)] py-1">
        {visible.length === 0 ? (
          <p className="px-3 py-2 text-xs text-[var(--fg-dim)]">No nodes</p>
        ) : (
          <ul>
            {visible.map((node) => (
              <li key={node.id}>
                <button
                  type="button"
                  aria-pressed={selectedId === node.id}
                  onClick={() => onSelect(node.id)}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-[var(--surface-0)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--accent-primary)]"
                >
                  {node.type ? (
                    <Badge kind="type" value={node.type} className="shrink-0" />
                  ) : null}
                  <span className="min-w-0 flex-1 truncate font-serif text-[var(--fg)]">
                    {node.content ?? node.id}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {nodes.length > MAX_VISIBLE ? (
          <p className="px-3 py-1 text-[10px] text-[var(--fg-dim)]">
            +{nodes.length - MAX_VISIBLE} more — use canvas
          </p>
        ) : null}
      </div>
    </details>
  );
}
