import { fetchJson } from "./client";
import { BackfillReportSchema, type BackfillReport } from "@/lib/schemas";

export function postBackfill(opts: { dry_run: boolean; project?: string }): Promise<BackfillReport> {
  return fetchJson(
    "/api/memory/lifecycle/backfill",
    {
      method: "POST",
      body: JSON.stringify(opts),
    },
    (d) => BackfillReportSchema.parse(d)
  );
}
