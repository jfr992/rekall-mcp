import { fetchJson } from "./client";
import { HealthSchema, type Health } from "@/lib/schemas";

export function getHealth(): Promise<Health> {
  return fetchJson("/health", undefined, (data) => HealthSchema.parse(data));
}
