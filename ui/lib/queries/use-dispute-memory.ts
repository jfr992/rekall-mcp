import { useMutation, useQueryClient } from "@tanstack/react-query";
import { disputeMemory } from "@/lib/api/dispute";
import { invalidateMemoryCaches } from "@/lib/queries/invalidate";
import type { DisputeResponse } from "@/lib/schemas";

export function useDisputeMemory() {
  const qc = useQueryClient();
  return useMutation<DisputeResponse, Error, { memoryId: string; disputed: boolean }>({
    mutationFn: ({ memoryId, disputed }) => disputeMemory(memoryId, disputed),
    onSuccess: () => invalidateMemoryCaches(qc),
  });
}
