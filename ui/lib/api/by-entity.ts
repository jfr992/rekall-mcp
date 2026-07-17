import { fetchJson } from "./client";
import { ByEntityResponseSchema, type ByEntityResponse } from "@/lib/schemas";

export function getByEntity(
  entity: string,
  project: string,
  limit = 20,
): Promise<ByEntityResponse> {
  const qs = new URLSearchParams({ entity, limit: String(limit) });
  if (project) qs.set("project", project);
  return fetchJson(`/api/memory/by-entity?${qs}`, undefined, (d) =>
    ByEntityResponseSchema.parse(d),
  );
}
