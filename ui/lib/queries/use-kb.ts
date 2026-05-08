import { useQuery } from "@tanstack/react-query";
import { getKb } from "@/lib/api/kb";

export function useKb(project: string) {
  return useQuery({
    queryKey: ["kb", project],
    queryFn: () => getKb(project),
    refetchOnWindowFocus: true,
    staleTime: 60_000,
  });
}
