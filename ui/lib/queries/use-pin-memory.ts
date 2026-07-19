import { useMutation, useQueryClient } from "@tanstack/react-query";
import { pinMemory } from "@/lib/api/pin";
import type { PinResponse } from "@/lib/schemas";

export function usePinMemory() {
  const qc = useQueryClient();
  return useMutation<PinResponse, Error, { memoryId: string; pinned: boolean }>({
    mutationFn: ({ memoryId, pinned }) => pinMemory(memoryId, pinned),
    onSuccess: (_data, { memoryId }) => {
      qc.invalidateQueries({ queryKey: ["memory-detail", memoryId] });
      for (const key of ["brain-graph", "kb", "pressure", "resume", "search", "by-entity"]) {
        qc.invalidateQueries({ queryKey: [key] });
      }
    },
  });
}
