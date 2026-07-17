import { useQuery } from "@tanstack/react-query";
import { postRecall } from "@/lib/api/search";

export function useSearch(query: string, project: string) {
  return useQuery({
    queryKey: ["search", project, query],
    queryFn: () => postRecall(query, project, 10),
    enabled: query.trim().length > 0,
    staleTime: 30_000,
  });
}
