import { fetchJson } from "./client";
import { DisputeResponseSchema, type DisputeResponse } from "@/lib/schemas";

export function disputeMemory(memoryId: string, disputed: boolean): Promise<DisputeResponse> {
  return fetchJson(
    `/api/memory/${encodeURIComponent(memoryId)}/dispute`,
    { method: "POST", body: JSON.stringify({ disputed }) },
    (d) => DisputeResponseSchema.parse(d),
  );
}
