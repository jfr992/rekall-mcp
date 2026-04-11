import { fetchJson } from "./client";
import { GraphResponseSchema, type GraphResponse } from "@/lib/schemas";

export function getGraph(project: string, limit = 400): Promise<GraphResponse> {
  const qs = new URLSearchParams({ project, limit: String(limit) });
  return fetchJson(`/api/memory/graph?${qs}`, undefined, (d) => GraphResponseSchema.parse(d));
}
