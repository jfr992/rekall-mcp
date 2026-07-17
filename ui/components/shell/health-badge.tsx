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
      className="flex shrink-0 items-center gap-2 rounded-md px-1 py-1"
      title={
        embedderError
          ? `Embedder is broken — ${embedderError}. Nothing can be embedded or recalled.`
          : status === "degraded"
            ? `${zeroVectors} sampled memories have zero embedding vectors — semantic search is broken for them`
            : undefined
      }
    >
      <span
        className="h-1.5 w-1.5 animate-pulse rounded-full"
        style={{ background: color, boxShadow: `0 0 8px ${color}` }}
      />
      <span className="font-mono text-[10px] font-medium uppercase tracking-[0.08em] text-[var(--fg-muted)]">
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
