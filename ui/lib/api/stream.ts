import { fetchJson } from "./client";
import { StreamResponseSchema, type StreamResponse } from "@/lib/schemas";

export function getStream(project: string, limit = 50): Promise<StreamResponse> {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (project) qs.set("project", project);
  return fetchJson(`/api/memory/stream?${qs}`, undefined, (d) =>
    StreamResponseSchema.parse(d)
  );
}
