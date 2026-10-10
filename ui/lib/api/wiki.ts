import { fetchJson } from "./client";
import {
  WikiIndexSchema,
  WikiSearchSchema,
  WikiPageSchema,
  WikiDraftsSchema,
  WikiCandidatesSchema,
} from "@/lib/schemas";

const JSON_HEADERS = { "Content-Type": "application/json" };

export function getWikiIndex(project: string) {
  const qs = new URLSearchParams();
  if (project) qs.set("project", project);
  return fetchJson(`/api/wiki/index?${qs}`, undefined, (d) => WikiIndexSchema.parse(d));
}
export function searchWiki(q: string, project: string) {
  const qs = new URLSearchParams({ q });
  if (project) qs.set("project", project);
  return fetchJson(`/api/wiki/search?${qs}`, undefined, (d) => WikiSearchSchema.parse(d));
}
export function getWikiPage(pageId: string, opts: { section?: string; full?: boolean } = {}) {
  const qs = new URLSearchParams();
  if (opts.section) qs.set("section", opts.section);
  if (opts.full) qs.set("full", "1");
  return fetchJson(`/api/wiki/page/${pageId}?${qs}`, undefined, (d) => WikiPageSchema.parse(d));
}
export function getWikiDrafts() {
  return fetchJson(`/api/wiki/drafts`, undefined, (d) => WikiDraftsSchema.parse(d));
}
export function approveDraft(pageId: string) {
  return fetchJson(`/api/wiki/drafts/${pageId}/approve`, { method: "POST" }, (d) => d as { page: Record<string, unknown> });
}
export function rejectDraft(pageId: string, reason: string) {
  return fetchJson(
    `/api/wiki/drafts/${pageId}/reject`,
    { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ reason }) },
    (d) => d as { status: string }
  );
}
export function editDraft(pageId: string, body: string) {
  return fetchJson(
    `/api/wiki/drafts/${pageId}`,
    { method: "PUT", headers: JSON_HEADERS, body: JSON.stringify({ body }) },
    (d) => d as { page: Record<string, unknown> }
  );
}
export function getWikiCandidates(project: string) {
  const qs = new URLSearchParams();
  if (project) qs.set("project", project);
  return fetchJson(`/api/wiki/candidates?${qs}`, undefined, (d) => WikiCandidatesSchema.parse(d));
}
export function createDraft(memoryIds: string[], pageType: string, title?: string) {
  return fetchJson(
    `/api/wiki/draft`,
    { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ memory_ids: memoryIds, page_type: pageType, title }) },
    (d) => d as { page?: Record<string, unknown>; needs?: string[]; status?: string }
  );
}
