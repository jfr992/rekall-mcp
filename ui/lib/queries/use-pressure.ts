import { useQuery } from "@tanstack/react-query";
import { getPressure } from "@/lib/api/pressure";

export function usePressure(project: string) {
  return useQuery({
    queryKey: ["pressure", project],
    queryFn: () => getPressure(project),
    staleTime: 30_000,
  });
}
