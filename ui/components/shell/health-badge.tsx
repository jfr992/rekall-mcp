"use client";

import { useHealth } from "@/lib/queries/use-health";

export function HealthBadge() {
  const { data, isError, isLoading } = useHealth();
  const status = isError ? "offline" : isLoading ? "…" : data?.status ?? "unknown";
  const color =
    status === "healthy" ? "var(--accent-success)" : isError ? "var(--accent-danger)" : "var(--fg-dim)";

  return (
    <div className="flex items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface-0)] px-3 py-2">
      <span
        className="h-2 w-2 rounded-full"
        style={{ background: color, boxShadow: `0 0 8px ${color}` }}
      />
      <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-[var(--fg-muted)]">
        {status}
      </span>
    </div>
  );
}
