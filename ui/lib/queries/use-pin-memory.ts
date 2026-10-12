import { useMutation, useQueryClient } from "@tanstack/react-query";
import { pinMemory } from "@/lib/api/pin";
import { invalidateMemoryCaches } from "@/lib/queries/invalidate";
import type { PinResponse } from "@/lib/schemas";

export function usePinMemory() {
  const qc = useQueryClient();
  return useMutation<PinResponse, Error, { memoryId: string; pinned: boolean }>({
    mutationFn: ({ memoryId, pinned }) => pinMemory(memoryId, pinned),
    onSuccess: () => invalidateMemoryCaches(qc),
  });
}
