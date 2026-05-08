import { useMutation, useQueryClient } from "@tanstack/react-query";
import { postBackfill } from "@/lib/api/backfill";
import type { BackfillReport } from "@/lib/schemas";

export function useBackfillMutation() {
  const qc = useQueryClient();
  return useMutation<BackfillReport, Error, { dry_run: boolean; project?: string }>({
    mutationFn: (vars) => postBackfill(vars),
    onSuccess: (_data, vars) => {
      if (!vars.dry_run) {
        qc.invalidateQueries({ queryKey: ["brain-graph"] });
        qc.invalidateQueries({ queryKey: ["kb"] });
      }
    },
  });
}
