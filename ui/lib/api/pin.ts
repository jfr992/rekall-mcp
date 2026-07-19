import { fetchJson } from "./client";
import { PinResponseSchema, type PinResponse } from "@/lib/schemas";

export function pinMemory(memoryId: string, pinned: boolean): Promise<PinResponse> {
  return fetchJson(
    `/api/memory/${encodeURIComponent(memoryId)}/pin`,
    { method: "POST", body: JSON.stringify({ pinned }) },
    (d) => PinResponseSchema.parse(d),
  );
}
