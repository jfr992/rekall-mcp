import { useQuery } from "@tanstack/react-query";
import { getInsights } from "@/lib/api/insights";

export function useInsights(project: string) {
  return useQuery({
    queryKey: ["insights", project],
    queryFn: () => getInsights(project),
    staleTime: 30_000,
  });
}
