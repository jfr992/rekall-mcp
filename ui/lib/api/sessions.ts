import { fetchJson } from "./client";
import {
  SessionsResponseSchema,
  SessionDetailSchema,
  type SessionsResponse,
  type SessionDetail,
} from "@/lib/schemas";

export function getSessions(project: string, limit = 50): Promise<SessionsResponse> {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (project) qs.set("project", project);
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
