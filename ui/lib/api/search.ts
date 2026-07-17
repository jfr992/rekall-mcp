import { fetchJson } from "./client";
import { RecallResponseSchema, type RecallResponse } from "@/lib/schemas";

export function postRecall(
  query: string,
  project: string,
  limit = 10,
): Promise<RecallResponse> {
  return fetchJson(
    "/api/memory/recall",
    {
      method: "POST",
      body: JSON.stringify({
        query,
        limit,
        ...(project ? { project } : {}),
      }),
    },
    (d) => RecallResponseSchema.parse(d),
  );
}
