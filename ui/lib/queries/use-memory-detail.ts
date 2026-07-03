import { useQuery } from "@tanstack/react-query";
import { getMemoryDetail } from "@/lib/api/detail";

export function useMemoryDetail(
  memoryId: string | null,
  currentProject?: string,
) {
  return useQuery({
    queryKey: ["memory-detail", memoryId, currentProject],
    queryFn: () => getMemoryDetail(memoryId as string, currentProject),
    enabled: Boolean(memoryId),
    staleTime: 30_000,
  });
}
