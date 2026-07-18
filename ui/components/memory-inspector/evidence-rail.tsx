"use client";

import { AlertTriangle } from "lucide-react";
import { MonoLabel } from "@/components/ui/mono-label";
import type { Provenance, Lifecycle, Storage } from "@/lib/schemas";

type Props = {
  provenance: Provenance | null | undefined;
  lifecycle: Lifecycle | null | undefined;
  storage: Storage | undefined;
  warnings: string[] | undefined;
  durability: number | null | undefined;
  salience: number | null | undefined;
  reinforcement_count: number | null | undefined;
  missingNeighborIds?: string[] | null;
};

const WARNING_LABELS: Record<string, string> = {
  missing_provenance: "missing provenance",
  scope_mismatch: "scope mismatch",
  missing_index: "not indexed in Qdrant",
  missing_lifecycle: "missing lifecycle data",
};

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-2 gap-2">
      <MonoLabel>{label}</MonoLabel>
      <span className="font-mono text-xs text-[var(--fg)] break-all">{value}</span>
    </div>
  );
}

export function EvidenceRail({
  provenance,
  lifecycle,
  storage,
  warnings,
  durability,
  salience,
  reinforcement_count,
  missingNeighborIds,
}: Props) {
  // Backend is the single source of truth for warnings — map codes to human labels
  const backendWarnings = (warnings ?? []).map((w) => WARNING_LABELS[w] ?? w);

  // Storage warnings are derived here — the backend emits no such warning
  const storageWarnings = [
    storage && storage.qdrant === false ? "not indexed in Qdrant" : null,
    storage && storage.yaml === false ? "missing from YAML" : null,
  ].filter((w): w is string => w !== null);

  const allWarnings = [...backendWarnings, ...storageWarnings];

  const hasSource = !!(
    provenance &&
    (provenance.agent ||
      provenance.source_tool ||
      provenance.repo_name ||
      provenance.repo_remote ||
      provenance.branch ||
      provenance.source_event)
  );

  const hasDurability = durability !== null && durability !== undefined;

  const hasSalience = salience !== null && salience !== undefined;

  const lifecycleLine = [
    lifecycle?.tier,
    lifecycle?.retention_days != null ? `retention ${lifecycle.retention_days}d` : null,
    reinforcement_count ? `reinforced ${reinforcement_count}×` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="space-y-4 border-t border-[var(--border)] pt-4 font-mono text-xs">
      {/* Source */}
      {hasSource && (
        <section>
          <MonoLabel className="mb-2 block">Source</MonoLabel>
          <div className="space-y-1">
            {provenance!.agent && <Field label="agent" value={provenance!.agent} />}
            {provenance!.source_tool && (
              <Field label="tool" value={provenance!.source_tool} />
            )}
            {provenance!.source_event && (
              <Field label="event" value={provenance!.source_event} />
            )}
            {provenance!.repo_name && (
              <Field label="repo" value={provenance!.repo_name} />
            )}
            {provenance!.repo_remote && (
              <Field label="remote" value={provenance!.repo_remote} />
            )}
            {provenance!.branch && <Field label="branch" value={provenance!.branch} />}
          </div>
        </section>
      )}

      {/* Lifecycle */}
      <section>
        <MonoLabel className="mb-2 block">Lifecycle</MonoLabel>
        <div className="space-y-1">
          {lifecycleLine && (
            <p className="text-xs text-[var(--fg)]">{lifecycleLine}</p>
          )}
          {hasDurability && (
            <div className="grid grid-cols-2 gap-2">
              <MonoLabel>durability</MonoLabel>
              <div
                role="meter"
                aria-label="durability"
                aria-valuenow={durability as number}
                aria-valuemin={0}
                aria-valuemax={1}
                title={(durability as number).toFixed(2)}
                className="h-1.5 w-full self-center overflow-hidden rounded-full bg-[rgba(45,212,160,0.12)]"
              >
                <div
                  className="h-full rounded-full bg-[var(--accent-primary)]"
                  style={{
                    width: `${Math.max(0, Math.min((durability as number) * 100, 100))}%`,
                  }}
                />
              </div>
            </div>
          )}
          {hasSalience && (
            <Field label="salience" value={(salience as number).toFixed(2)} />
          )}
        </div>
      </section>

      {/* Warnings */}
      {(allWarnings.length > 0 || (missingNeighborIds?.length ?? 0) > 0) && (
        <section>
          <MonoLabel className="mb-2 block">Warnings</MonoLabel>
          <ul className="space-y-1">
            {allWarnings.map((w) => (
              <li key={w} className="flex items-start gap-2">
                <AlertTriangle
                  size={12}
                  className="mt-0.5 shrink-0 text-[var(--accent-warning)]"
                />
                <span className="text-xs text-[var(--fg-muted)]">{w}</span>
              </li>
            ))}
            {missingNeighborIds && missingNeighborIds.length > 0 && (
              <li key="missing-neighbors" className="flex items-start gap-2">
                <AlertTriangle
                  size={12}
                  className="mt-0.5 shrink-0 text-[var(--accent-warning)]"
                />
                <span className="text-xs text-[var(--fg-muted)]">
                  graph edges point to {missingNeighborIds.length} missing memorie(s):{" "}
                  {missingNeighborIds.join(", ")}
                </span>
              </li>
            )}
          </ul>
        </section>
      )}
    </div>
  );
}
