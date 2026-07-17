import { useQuery } from "@tanstack/react-query";
import { getStream } from "@/lib/api/stream";

// One stream poll per page — panels derive from this query's cache (no SSE).
export function useStream(project: string, limit = 50) {
  return useQuery({
    queryKey: ["stream", project, limit],
    queryFn: () => getStream(project, limit),
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
}
