import { useQuery } from "@tanstack/react-query";
import { getHealth } from "@/lib/api/health";

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
}
