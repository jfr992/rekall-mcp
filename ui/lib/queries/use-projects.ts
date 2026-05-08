import { useQuery } from "@tanstack/react-query";
import { getProjects } from "@/lib/api/projects";

export function useProjects() {
  return useQuery({
    queryKey: ["projects"],
    queryFn: getProjects,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}
