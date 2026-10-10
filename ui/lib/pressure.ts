import type { PressureResponse } from "@/lib/schemas";

// Older servers omit prune_candidates_count; low + stale then double-counts overlap.
export function pruneCount(f: PressureResponse["flagged"]): number {
  return f.prune_candidates_count ?? f.low_value_count + f.stale_working_count;
}
