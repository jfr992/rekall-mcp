"use client";

import { useHealth } from "@/lib/queries/use-health";

export function HealthBadge() {
  const { data, isError, isLoading } = useHealth();
  const status = isError ? "offline" : isLoading ? "…" : (data?.status ?? "unknown");
  const zeroVectors = data?.vectors?.zero_vectors ?? 0;
  const embedderError =
    typeof data?.embedder === "object" ? data.embedder.error : undefined;
  const color =
    status === "healthy"
      ? "var(--accent-success)"
      : status === "degraded"
        ? "var(--accent-warning, #d97706)"
        : isError
          ? "var(--accent-danger)"
          : "var(--fg-dim)";

  return (
    <div
      className="flex items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface-0)] px-3 py-2"
      title={
        embedderError
          ? `Embedder is broken — ${embedderError}. Nothing can be embedded or recalled.`
          : status === "degraded"
            ? `${zeroVectors} sampled memories have zero embedding vectors — semantic search is broken for them`
            : undefined
      }
    >
      <span
        className="h-2 w-2 rounded-full"
        style={{ background: color, boxShadow: `0 0 8px ${color}` }}
      />
      <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-[var(--fg-muted)]">
        {status}
        {embedderError
          ? " · embedder down"
          : status === "degraded"
            ? ` · ${zeroVectors} dead vectors`
            : ""}
      </span>
    </div>
  );
}
