import { useMutation, useQueryClient } from "@tanstack/react-query";
import { deleteMemory } from "@/lib/api/delete";
import type { DeleteResponse } from "@/lib/schemas";

export function useDeleteMemory() {
  const qc = useQueryClient();
  return useMutation<DeleteResponse, Error, { memoryId: string }>({
    mutationFn: ({ memoryId }) => deleteMemory(memoryId),
    onSuccess: (_data, { memoryId }) => {
      qc.removeQueries({ queryKey: ["memory-detail", memoryId] });
      for (const key of ["brain-graph", "kb", "pressure", "resume", "search", "by-entity"]) {
        qc.invalidateQueries({ queryKey: [key] });
      }
    },
  });
}
