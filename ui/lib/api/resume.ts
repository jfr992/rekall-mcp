import { fetchJson } from "./client";
import { ResumeResponseSchema, type ResumeResponse } from "@/lib/schemas";

export function getResume(project: string): Promise<ResumeResponse> {
  const qs = new URLSearchParams();
  if (project) qs.set("project", project);
  return fetchJson(`/api/memory/resume?${qs}`, undefined, (d) => ResumeResponseSchema.parse(d));
}
