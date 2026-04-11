import { fetchJson } from "./client";
import { KbResponseSchema, type KbResponse } from "@/lib/schemas";

export function getKb(project: string): Promise<KbResponse> {
  const qs = new URLSearchParams({ project });
  return fetchJson(`/api/memory/kb?${qs}`, undefined, (d) => KbResponseSchema.parse(d));
}
