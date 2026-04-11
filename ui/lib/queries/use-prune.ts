import { useMutation, useQueryClient } from "@tanstack/react-query";
import { postPrunePlan, postPruneApply } from "@/lib/api/prune";
import type { PrunePlan, PruneApplyResponse } from "@/lib/schemas";

export function usePrunePlanMutation() {
  return useMutation<PrunePlan, Error, { project: string; limit?: number }>({
    mutationFn: ({ project, limit }) => postPrunePlan(project, limit),
  });
}

export function usePruneApplyMutation() {
  const qc = useQueryClient();
  return useMutation<PruneApplyResponse, Error, { planId: string; confirm: string }>({
    mutationFn: ({ planId, confirm }) => postPruneApply(planId, confirm),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["brain-graph"] });
      qc.invalidateQueries({ queryKey: ["pressure"] });
      qc.invalidateQueries({ queryKey: ["kb"] });
      qc.invalidateQueries({ queryKey: ["resume"] });
    },
  });
}
