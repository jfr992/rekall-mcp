import { fetchJson } from "./client";
import { DetailResponseV2Schema, type DetailResponseV2 } from "@/lib/schemas";

export function getMemoryDetail(
  memoryId: string,
  currentProject?: string,
): Promise<DetailResponseV2> {
  const qs = currentProject
    ? `?current_project=${encodeURIComponent(currentProject)}`
    : "";
  return fetchJson(
    `/api/memory/detail/${encodeURIComponent(memoryId)}${qs}`,
    undefined,
    (d) => DetailResponseV2Schema.parse(d),
  );
}
