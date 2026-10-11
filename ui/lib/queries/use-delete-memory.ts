import { useMutation, useQueryClient } from "@tanstack/react-query";
import { deleteMemory } from "@/lib/api/delete";
import { invalidateMemoryCaches } from "@/lib/queries/invalidate";
import type { DeleteResponse } from "@/lib/schemas";

export function useDeleteMemory() {
  const qc = useQueryClient();
  return useMutation<DeleteResponse, Error, { memoryId: string }>({
    mutationFn: ({ memoryId }) => deleteMemory(memoryId),
    onSuccess: (_data, { memoryId }) => {
      qc.removeQueries({ queryKey: ["memory-detail", memoryId] });
      invalidateMemoryCaches(qc);
    },
  });
}
