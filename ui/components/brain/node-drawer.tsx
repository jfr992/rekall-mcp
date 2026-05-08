"use client";

import { Drawer } from "@/components/ui/drawer";
import { Badge } from "@/components/ui/badge";
import { MonoLabel } from "@/components/ui/mono-label";
import { SerifHeading } from "@/components/ui/serif-heading";
import { Skeleton } from "@/components/ui/skeleton";
import { AlertTriangle } from "lucide-react";
import type { DetailResponse } from "@/lib/schemas";

type Props = {
  open: boolean;
  detail: DetailResponse | undefined;
  isLoading: boolean;
  onClose: () => void;
};

export function NodeDrawer({ open, detail, isLoading, onClose }: Props) {
  const memory = detail?.memory;
  const hasContradicts =
    detail?.neighbors.some((n) => n.relation === "contradicts") ?? false;

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={
        isLoading || !memory ? (
          <Skeleton className="h-6 w-48" />
        ) : (
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
              {memory.type ? <Badge kind="type" value={memory.type} /> : null}
              {memory.tier ? <Badge kind="tier" value={memory.tier} /> : null}
            </div>
            <MonoLabel>{memory.memory_id}</MonoLabel>
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
          <SerifHeading title={memory.content?.slice(0, 120) ?? ""} size="section" />
          <p className="text-sm leading-relaxed text-[var(--fg)]">{memory.content}</p>

          <div className="grid grid-cols-2 gap-3 border-y border-[var(--border)] py-3 font-mono text-xs">
            <div>
              <MonoLabel>date</MonoLabel>
              <div className="text-[var(--fg)]">{memory.date ?? "—"}</div>
            </div>
            <div>
              <MonoLabel>durability</MonoLabel>
              <div className="text-[var(--fg)]">
                {(memory.durability ?? 0).toFixed(2)}
              </div>
            </div>
            <div>
              <MonoLabel>reinforced</MonoLabel>
              <div className="text-[var(--fg)]">
                {memory.reinforcement_count ?? 0}×
              </div>
            </div>
            <div>
              <MonoLabel>salience</MonoLabel>
              <div className="text-[var(--fg)]">
                {memory.salience !== undefined
                  ? memory.salience.toFixed(2)
                  : "—"}
              </div>
            </div>
          </div>

          {hasContradicts ? (
            <div className="flex items-start gap-2 rounded-md border border-[var(--accent-danger)]/40 bg-[var(--accent-danger)]/10 p-3">
              <AlertTriangle
                size={16}
                className="mt-0.5 shrink-0 text-[var(--accent-danger)]"
              />
              <p className="text-xs text-[var(--fg)]">
                This memory has contradicting neighbors.
              </p>
            </div>
          ) : null}

          {detail?.neighbors?.length ? (
            <section>
              <MonoLabel>neighbors · {detail.neighbors.length}</MonoLabel>
              <ul className="mt-2 space-y-2">
                {detail.neighbors.map((n, i) => (
                  <li
                    key={`${n.memory.memory_id}-${i}`}
                    className="rounded-md border border-[var(--border)] bg-[var(--surface-0)] p-3"
                  >
                    <div className="mb-1 flex items-center gap-2">
                      <Badge kind="type" value={n.memory.type ?? "note"} />
                      <MonoLabel>{n.relation}</MonoLabel>
                    </div>
                    <p className="text-xs text-[var(--fg-muted)]">
                      {n.memory.content}
                    </p>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      ) : (
        <p className="text-sm text-[var(--fg-muted)]">Memory not found.</p>
      )}
    </Drawer>
  );
}
