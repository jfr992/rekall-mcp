import { fetchJson } from "./client";
import { PressureResponseSchema, type PressureResponse } from "@/lib/schemas";

export function getPressure(project: string): Promise<PressureResponse> {
  const qs = new URLSearchParams();
  if (project) qs.set("project", project);
  return fetchJson(`/api/memory/pressure?${qs}`, undefined, (d) => PressureResponseSchema.parse(d));
}
