import { fetchJson } from "./client";
import { DetailResponseSchema, type DetailResponse } from "@/lib/schemas";

export function getMemoryDetail(memoryId: string): Promise<DetailResponse> {
  return fetchJson(`/api/memory/detail/${encodeURIComponent(memoryId)}`, undefined, (d) =>
    DetailResponseSchema.parse(d)
  );
}
