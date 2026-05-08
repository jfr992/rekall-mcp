import { useQuery } from "@tanstack/react-query";
import { getResume } from "@/lib/api/resume";

export function useResume(project: string) {
  return useQuery({
    queryKey: ["resume", project],
    queryFn: () => getResume(project),
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}
