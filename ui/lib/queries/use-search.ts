import { useQuery } from "@tanstack/react-query";
import { postRecall } from "@/lib/api/search";

export type SearchMode = "semantic" | "exact";

// Exact mode fetches a deeper pool (50): the verbatim match may rank low
// semantically, so the caller client-filters the wider set to substring hits.
const LIMIT: Record<SearchMode, number> = { semantic: 10, exact: 50 };

export function useSearch(
  query: string,
  project: string,
  mode: SearchMode = "semantic",
  limit: number = LIMIT[mode],
) {
  return useQuery({
    queryKey: ["search", project, query, mode, limit],
    queryFn: () => postRecall(query, project, limit),
    enabled: query.trim().length > 0,
    staleTime: 30_000,
  });
}
