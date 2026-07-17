import { fetchJson } from "./client";
import { InsightsResponseSchema, type InsightsResponse } from "@/lib/schemas";

export function getInsights(project: string): Promise<InsightsResponse> {
  const qs = new URLSearchParams();
  if (project) qs.set("project", project);
  const suffix = qs.size ? `?${qs}` : "";
  return fetchJson(`/api/memory/insights${suffix}`, undefined, (d) =>
    InsightsResponseSchema.parse(d)
  );
}
