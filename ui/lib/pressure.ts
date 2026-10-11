import type { PressureResponse } from "@/lib/schemas";

// Older servers omit prune_candidates_count; low + stale then double-counts overlap.
export function pruneCount(f: PressureResponse["flagged"]): number {
  return f.prune_candidates_count ?? f.low_value_count + f.stale_working_count;
}

export type Attention = { total: number; prune: number; conflict: number; disputed: number; staleCandidates: number };

export function attentionCount(f: PressureResponse["flagged"]): Attention {
  const prune = pruneCount(f);
  const conflict = f.contradiction_count;
  const disputed = f.disputed_count;
  const staleCandidates = f.stale_candidates_count;
  return { total: prune + conflict + disputed + staleCandidates, prune, conflict, disputed, staleCandidates };
}
