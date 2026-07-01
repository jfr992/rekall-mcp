import { useQuery } from "@tanstack/react-query";
import { getPublishPreview } from "@/lib/api/publish";

export function usePublish(project: string, enabled: boolean) {
  return useQuery({
    queryKey: ["publish", project],
    queryFn: () => getPublishPreview(project),
    enabled,
  });
}
