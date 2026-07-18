import { fetchJson } from "./client";
import { StreamResponseSchema, type StreamResponse } from "@/lib/schemas";

// Inclusive YYYY-MM-DD day bounds; omitted keys leave the feed unbounded.
export type StreamRange = { after?: string; before?: string };

export function getStream(
  project: string,
  limit = 50,
  range: StreamRange = {}
): Promise<StreamResponse> {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (project) qs.set("project", project);
  if (range.after) qs.set("after", range.after);
  if (range.before) qs.set("before", range.before);
  return fetchJson(`/api/memory/stream?${qs}`, undefined, (d) =>
    StreamResponseSchema.parse(d)
  );
}
