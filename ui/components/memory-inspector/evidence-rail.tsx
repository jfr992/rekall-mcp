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
  salience: number | undefined;
  reinforcement_count: number | null | undefined;
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
}: Props) {
  // Backend is the single source of truth for warnings — map codes to human labels
  const allWarnings = (warnings ?? []).map((w) => WARNING_LABELS[w] ?? w);

  // Null/undefined → "unknown"; explicit 0 → "0.00"
  const durabilityDisplay = durability == null ? "unknown" : durability.toFixed(2);

  // Absent → "legacy/unknown"; present → formatted
  const salienceDisplay =
    salience !== undefined ? salience.toFixed(2) : "legacy/unknown";

  // Null/undefined → "unknown"; number (including 0) → "N×"
  const reinforcementDisplay =
    reinforcement_count == null ? "unknown" : `${reinforcement_count}×`;

  return (
    <div className="space-y-4 border-t border-[var(--border)] pt-4 font-mono text-xs">
      {/* Source */}
      {provenance && (() => {
        const hasAnyField = !!(
          provenance.agent ||
          provenance.source_tool ||
          provenance.source_event ||
          provenance.repo_name ||
          provenance.branch ||
          provenance.trust_boundary
        );
        return (
          <section>
            <MonoLabel className="mb-2 block">Source</MonoLabel>
            {hasAnyField ? (
              <div className="space-y-1">
                {provenance.agent && (
                  <Field label="agent" value={provenance.agent} />
                )}
                {provenance.source_tool && (
                  <Field label="tool" value={provenance.source_tool} />
                )}
                {provenance.source_event && (
                  <Field label="event" value={provenance.source_event} />
                )}
                {provenance.repo_name && (
                  <Field label="repo" value={provenance.repo_name} />
                )}
                {provenance.branch && (
                  <Field label="branch" value={provenance.branch} />
                )}
                {provenance.trust_boundary && (
                  <Field label="trust" value={provenance.trust_boundary} />
                )}
              </div>
            ) : (
              <p className="text-xs text-[var(--fg-muted)]">no provenance recorded (legacy memory)</p>
            )}
          </section>
        );
      })()}

      {/* Lifecycle */}
      <section>
        <MonoLabel className="mb-2 block">Lifecycle</MonoLabel>
        <div className="space-y-1">
          {lifecycle?.tier && <Field label="tier" value={lifecycle.tier} />}
          <Field label="durability" value={durabilityDisplay} />
          <Field label="salience" value={salienceDisplay} />
          <Field label="reinforcement" value={reinforcementDisplay} />
          {lifecycle?.lifecycle_reason && (
            <Field label="reason" value={lifecycle.lifecycle_reason} />
          )}
          {lifecycle?.retention_days != null && (
            <Field label="retention" value={`${lifecycle.retention_days}d`} />
          )}
        </div>
      </section>

      {/* Storage */}
      {storage && (
        <section>
          <MonoLabel className="mb-2 block">Storage</MonoLabel>
          <div className="space-y-1">
            <Field label="qdrant" value={storage.qdrant ? "indexed" : "not indexed"} />
            <Field label="yaml" value={storage.yaml ? "persisted" : "not persisted"} />
          </div>
        </section>
      )}

      {/* Warnings */}
      {allWarnings.length > 0 && (
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
          </ul>
        </section>
      )}
    </div>
  );
}
