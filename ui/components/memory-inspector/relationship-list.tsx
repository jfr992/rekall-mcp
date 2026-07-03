"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { MonoLabel } from "@/components/ui/mono-label";
import type { Relationship } from "@/lib/schemas";

// Human-readable label per relation × direction
function directionLabel(relation: string, direction: "in" | "out"): string {
  if (direction === "out") {
    const map: Record<string, string> = {
      supersedes: "supersedes",
      depends_on: "depends on",
      led_to: "led to",
      related_to: "related to",
      contradicts: "contradicts",
    };
    return map[relation] ?? relation.replace(/_/g, " ");
  }
  // direction === "in": passive / inverted form
  const map: Record<string, string> = {
    supersedes: "superseded by",
    depends_on: "depended on by",
    led_to: "derived from",
    related_to: "related to",
    contradicts: "contradicted by",
  };
  return map[relation] ?? `← ${relation.replace(/_/g, " ")}`;
}

// Contradictions first, then supersedes, depends_on, led_to, related_to
const RELATION_ORDER = [
  "contradicts",
  "supersedes",
  "depends_on",
  "led_to",
  "related_to",
];

function sortedRelationships(rels: Relationship[]): Relationship[] {
  return [...rels].sort((a, b) => {
    const ai = RELATION_ORDER.indexOf(a.relation);
    const bi = RELATION_ORDER.indexOf(b.relation);
    return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
  });
}

type Props = {
  relationships: Relationship[];
  onSelectMemory: (memoryId: string) => void;
};

export function RelationshipList({ relationships, onSelectMemory }: Props) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  if (!relationships.length) return null;

  const sorted = sortedRelationships(relationships);

  return (
    <section>
      <MonoLabel className="mb-2 block">
        relationships · {relationships.length}
      </MonoLabel>
      <ul className="space-y-2">
        {sorted.map((rel, i) => {
          const mem = rel.memory;
          const label = directionLabel(rel.relation, rel.direction);
          const targetId = rel.neighbor_id;
          const isExpanded = expanded[targetId] ?? false;

          return (
            <li key={`${targetId}-${i}`}>
              <div className="relative">
                {/* Navigation button — navigate to neighbor on click */}
                <button
                  type="button"
                  onClick={() => onSelectMemory(targetId)}
                  className="flex min-h-[44px] w-full items-start gap-3 rounded-md border border-[var(--border)] bg-[var(--surface-0)] px-3 py-2 text-left motion-safe:transition-colors hover:border-[var(--fg-muted)]/40 hover:bg-[var(--bg-elevated)]"
                >
                  <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <MonoLabel>{label}</MonoLabel>
                      {mem?.type ? (
                        <Badge kind="type" value={mem.type} />
                      ) : null}
                      {mem?.tier ? (
                        <Badge kind="tier" value={mem.tier} />
                      ) : null}
                      {mem?.date ? (
                        <MonoLabel>{mem.date}</MonoLabel>
                      ) : null}
                      {mem?.project ? (
                        <MonoLabel>{mem.project}</MonoLabel>
                      ) : null}
                    </div>
                    {mem ? (
                      mem.content ? (
                        <span
                          className={`break-words text-xs text-[var(--fg-muted)] ${isExpanded ? "" : "line-clamp-2"}`}
                        >
                          {mem.content}
                        </span>
                      ) : null
                    ) : (
                      <span className="text-xs italic text-[var(--fg-muted)]">
                        memory unavailable
                      </span>
                    )}
                    {mem?.memory_id ? (
                      <span className="break-all font-mono text-[10px] text-[var(--fg-muted)]">
                        {mem.memory_id}
                      </span>
                    ) : null}
                  </div>
                  <ChevronRight
                    size={14}
                    className="mt-1 shrink-0 text-[var(--fg-muted)]"
                  />
                </button>

                {/* Expand toggle — separate from navigation; stops propagation */}
                {mem?.content ? (
                  <button
                    type="button"
                    aria-expanded={isExpanded}
                    onClick={(e) => {
                      e.stopPropagation();
                      setExpanded((prev) => ({
                        ...prev,
                        [targetId]: !prev[targetId],
                      }));
                    }}
                    className="absolute bottom-1.5 right-8 font-mono text-[10px] text-[var(--fg-muted)] hover:text-[var(--fg)]"
                  >
                    {isExpanded ? "collapse" : "expand"}
                  </button>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
