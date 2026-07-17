import { fetchJson } from "./client";
import { DeleteResponseSchema, type DeleteResponse } from "@/lib/schemas";

export function deleteMemory(memoryId: string): Promise<DeleteResponse> {
  return fetchJson(
    `/api/memory/${encodeURIComponent(memoryId)}`,
    { method: "DELETE" },
    (d) => DeleteResponseSchema.parse(d),
  );
}
