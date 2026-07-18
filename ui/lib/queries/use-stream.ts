import { useQuery } from "@tanstack/react-query";
import { getStream, type StreamRange } from "@/lib/api/stream";

// One stream poll per page — panels derive from this query's cache (no SSE).
export function useStream(project: string, limit = 50, range: StreamRange = {}) {
  return useQuery({
    queryKey: ["stream", project, limit, range.after ?? null, range.before ?? null],
    queryFn: () => getStream(project, limit, range),
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
}
