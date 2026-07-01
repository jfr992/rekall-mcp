import { fetchJson } from "./client";
import { PublishResponseSchema, type PublishResponse } from "@/lib/schemas";

export function getPublishPreview(project: string): Promise<PublishResponse> {
  const qs = new URLSearchParams(project ? { project } : {});
  return fetchJson(`/api/memory/publish?${qs}`, undefined, (d) =>
    PublishResponseSchema.parse(d)
  );
}

export function downloadBundleUrl(project: string): string {
  const qs = new URLSearchParams({ mode: "tar", ...(project ? { project } : {}) });
  return `/api/memory/publish?${qs}`;
}
