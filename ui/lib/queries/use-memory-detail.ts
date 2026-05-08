import { useQuery } from "@tanstack/react-query";
import { getMemoryDetail } from "@/lib/api/detail";

export function useMemoryDetail(memoryId: string | null) {
  return useQuery({
    queryKey: ["memory-detail", memoryId],
    queryFn: () => getMemoryDetail(memoryId as string),
    enabled: Boolean(memoryId),
    staleTime: 30_000,
  });
}
