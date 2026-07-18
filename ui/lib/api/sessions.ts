import { fetchJson } from "./client";
import {
  SessionsResponseSchema,
  SessionDetailSchema,
  type SessionsResponse,
  type SessionDetail,
} from "@/lib/schemas";

// Inclusive YYYY-MM-DD day bounds; omitted keys leave the list unbounded.
export type SessionsRange = { after?: string; before?: string };

export function getSessions(
  project: string,
  limit = 50,
  range: SessionsRange = {}
): Promise<SessionsResponse> {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (project) qs.set("project", project);
  if (range.after) qs.set("after", range.after);
  if (range.before) qs.set("before", range.before);
  return fetchJson(`/api/memory/sessions?${qs}`, undefined, (d) =>
    SessionsResponseSchema.parse(d)
  );
}

export function getSessionDetail(sessionId: string): Promise<SessionDetail> {
  return fetchJson(
    `/api/memory/sessions/${encodeURIComponent(sessionId)}`,
    undefined,
    (d) => SessionDetailSchema.parse(d)
  );
}
