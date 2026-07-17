"use client";

import { useState } from "react";
import { AlertTriangle, Copy, Check, X } from "lucide-react";
import { Drawer } from "@/components/ui/drawer";
import { Badge } from "@/components/ui/badge";
import { MonoLabel } from "@/components/ui/mono-label";
import { Skeleton } from "@/components/ui/skeleton";
import { MemoryContent } from "./memory-content";
import { EntityBacklinks } from "./entity-backlinks";
import { EvidenceRail } from "./evidence-rail";
import { RelationshipList } from "./relationship-list";
import type { DetailResponseV2 } from "@/lib/schemas";

type Props = {
  open: boolean;
  detail: DetailResponseV2 | undefined;
  isLoading: boolean;
  currentProject: string;
  onClose: () => void;
  onSelectMemory: (memoryId: string) => void;
};

export function MemoryInspector({
  open,
  detail,
  isLoading,
  currentProject,
  onClose,
  onSelectMemory,
}: Props) {
  const [copied, setCopied] = useState<"id" | "content" | null>(null);
  const [copyFailed, setCopyFailed] = useState<"id" | "content" | null>(null);
  const [backlinkEntity, setBacklinkEntity] = useState<string | null>(null);
  const memory = detail?.memory;

  // Compute status: contradicted > superseded > legacy > current
  const statusValue = (() => {
    const rels = detail?.relationships ?? [];
    const warnings = detail?.warnings ?? [];
    if (rels.some((r) => r.relation === "contradicts")) return "contradicted";
    if (rels.some((r) => r.direction === "in" && r.relation === "supersedes"))
      return "superseded";
    if (warnings.includes("missing_provenance")) return "legacy";
    return "current";
  })();

  // Contradiction banner: any contradicts edge (in or out)
  const hasContradiction = statusValue === "contradicted";

  function copyText(text: string, kind: "id" | "content") {
    navigator.clipboard
      .writeText(text)
      .then(() => {
        setCopied(kind);
        setTimeout(() => setCopied(null), 1500);
      })
      .catch(() => {
        // Fallback: try execCommand via temp textarea
        let ok = false;
        try {
          const el = document.createElement("textarea");
          el.value = text;
          el.style.cssText = "position:fixed;opacity:0;pointer-events:none";
          document.body.appendChild(el);
          el.select();
          ok = document.execCommand("copy");
          document.body.removeChild(el);
        } catch {
          ok = false;
        }
        if (ok) {
          setCopied(kind);
          setTimeout(() => setCopied(null), 1500);
        } else {
          setCopyFailed(kind);
          setTimeout(() => setCopyFailed(null), 2000);
        }
      });
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      ariaLabel="Memory details"
      title={
        isLoading || !memory ? (
          <Skeleton className="h-6 w-48" />
        ) : (
          <div className="flex flex-col gap-2">
            <span className="text-sm font-semibold text-[var(--fg)]">
              Memory details
            </span>
            <div className="flex flex-wrap items-center gap-2">
              {memory.type ? <Badge kind="type" value={memory.type} /> : null}
              {memory.tier ? <Badge kind="tier" value={memory.tier} /> : null}
              {memory.project ? (
                <span className="font-mono text-[11px] text-[var(--fg-muted)]">
                  {memory.project}
                </span>
              ) : null}
              <Badge kind="status" value={statusValue} />
            </div>
            <div className="flex items-center gap-1">
              <MonoLabel className="break-all">{memory.memory_id}</MonoLabel>
              <button
                type="button"
                aria-label={copyFailed === "id" ? "Copy failed" : "Copy memory ID"}
                onClick={() => copyText(memory.memory_id, "id")}
                className="rounded p-0.5 text-[var(--fg-muted)] hover:text-[var(--fg)]"
              >
                {copied === "id" ? (
                  <Check size={12} />
                ) : copyFailed === "id" ? (
                  <X size={12} />
                ) : (
                  <Copy size={12} />
                )}
              </button>
              {memory.content ? (
                <button
                  type="button"
                  aria-label={
                    copyFailed === "content" ? "Copy failed" : "Copy memory content"
                  }
                  onClick={() => copyText(memory.content!, "content")}
                  className="rounded p-0.5 text-[var(--fg-muted)] hover:text-[var(--fg)]"
                >
                  {copied === "content" ? (
                    <Check size={12} />
                  ) : copyFailed === "content" ? (
                    <X size={12} />
                  ) : (
                    <Copy size={12} />
                  )}
                </button>
              ) : null}
            </div>
          </div>
        )
      }
    >
      {isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-8 w-3/4" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : memory ? (
        <div className="space-y-5">
          {/* Contradiction warning — checks both in and out relationships */}
          {hasContradiction && (
            <div className="flex items-start gap-2 rounded-md border border-[var(--accent-danger)]/40 bg-[var(--accent-danger)]/10 p-3">
              <AlertTriangle
                size={16}
                className="mt-0.5 shrink-0 text-[var(--accent-danger)]"
              />
              <p className="text-xs text-[var(--fg)]">
                This memory has contradicting relationships.
              </p>
            </div>
          )}

          {/* Memory text — rendered once */}
          <MemoryContent content={memory.content ?? ""} />

          {/* Entity chips — each opens the backlinks slide-over */}
          {memory.entities?.length ? (
            <div className="flex flex-wrap gap-1.5">
              {memory.entities.map((entity) => (
                <button
                  key={entity}
                  type="button"
                  aria-label={`Backlinks for ${entity}`}
                  onClick={() => setBacklinkEntity(entity)}
                  className="rounded-full border border-[var(--border)] bg-[var(--surface-0)] px-2.5 py-0.5 font-mono text-[11px] text-[var(--fg-muted)] hover:border-[var(--border-strong)] hover:text-[var(--fg)]"
                >
                  {entity}
                </button>
              ))}
            </div>
          ) : null}
          {backlinkEntity && (
            <EntityBacklinks
              entity={backlinkEntity}
              project={currentProject}
              onClose={() => setBacklinkEntity(null)}
              onSelectMemory={(memoryId) => {
                setBacklinkEntity(null);
                onSelectMemory(memoryId);
              }}
            />
          )}

          {/* Evidence rail */}
          <EvidenceRail
            provenance={detail?.provenance}
            lifecycle={detail?.lifecycle}
            storage={detail?.storage}
            warnings={detail?.warnings}
            durability={detail?.lifecycle?.durability}
            salience={memory.salience}
            reinforcement_count={memory.reinforcement_count}
            missingNeighborIds={detail?.missing_neighbor_ids}
          />

          {/* Relationship list */}
          {detail?.relationships?.length ? (
            <RelationshipList
              relationships={detail.relationships}
              onSelectMemory={onSelectMemory}
            />
          ) : null}
        </div>
      ) : (
        <p className="text-sm text-[var(--fg-muted)]">Memory not found.</p>
      )}
    </Drawer>
  );
}
