import { useMutation, useQueryClient } from "@tanstack/react-query";
import { disputeMemory } from "@/lib/api/dispute";
import type { DisputeResponse } from "@/lib/schemas";

export function useDisputeMemory() {
  const qc = useQueryClient();
  return useMutation<DisputeResponse, Error, { memoryId: string; disputed: boolean }>({
    mutationFn: ({ memoryId, disputed }) => disputeMemory(memoryId, disputed),
    onSuccess: (_data, { memoryId }) => {
      qc.invalidateQueries({ queryKey: ["memory-detail", memoryId] });
      qc.invalidateQueries({ queryKey: ["pressure"] });
    },
  });
}
