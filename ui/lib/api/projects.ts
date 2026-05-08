import { fetchJson } from "./client";
import { ProjectsResponseSchema, type ProjectsResponse } from "@/lib/schemas";

export function getProjects(): Promise<ProjectsResponse> {
  return fetchJson("/api/memory/projects", undefined, (d) => ProjectsResponseSchema.parse(d));
}
