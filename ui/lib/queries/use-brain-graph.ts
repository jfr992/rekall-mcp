import { useQuery } from "@tanstack/react-query";
import { getGraph } from "@/lib/api/graph";

export function useBrainGraph(project: string, limit = 400) {
  return useQuery({
    queryKey: ["brain-graph", project, limit],
    queryFn: () => getGraph(project, limit),
    refetchInterval: 5_000,
    staleTime: 2_000,
  });
}
