import { fetchJson } from "./client";
import {
  PrunePlanSchema,
  PruneApplyResponseSchema,
  type PrunePlan,
  type PruneApplyResponse,
} from "@/lib/schemas";

export function postPrunePlan(project: string, limit = 200): Promise<PrunePlan> {
  return fetchJson(
    "/api/memory/prune/plan",
    {
      method: "POST",
      body: JSON.stringify({ project, limit }),
    },
    (d) => PrunePlanSchema.parse(d)
  );
}

export function postPruneApply(planId: string, confirm: string): Promise<PruneApplyResponse> {
  return fetchJson(
    "/api/memory/prune/apply",
    {
      method: "POST",
      body: JSON.stringify({ plan_id: planId, confirm }),
    },
    (d) => PruneApplyResponseSchema.parse(d)
  );
}
