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

export interface SynthStart {
  status: "started" | "running" | "unconfigured";
  hint?: string;
}

export async function startSynthesis(project: string): Promise<SynthStart> {
  const qs = new URLSearchParams(project ? { project } : {});
  return fetchJson(`/api/memory/publish/synthesize?${qs}`, { method: "POST" });
}

export interface SynthStatus {
  status: "idle" | "running" | "done" | "error";
  done?: number;
  total?: number;
  error?: string;
}

export async function getSynthesisStatus(project: string): Promise<SynthStatus> {
  const qs = new URLSearchParams(project ? { project } : {});
  return fetchJson(`/api/memory/publish/status?${qs}`);
}
