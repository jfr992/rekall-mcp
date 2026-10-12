import type { QueryClient } from "@tanstack/react-query";

export const MEMORY_MUTATION_KEYS = [
  "brain-graph", "kb", "pressure", "resume", "search", "by-entity", "insights", "projects", "stream", "memory-detail", "sessions", "session-detail",
] as const;

export function invalidateMemoryCaches(qc: QueryClient): void {
  for (const key of MEMORY_MUTATION_KEYS) qc.invalidateQueries({ queryKey: [key] });
}
