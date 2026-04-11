"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { SerifHeading } from "@/components/ui/serif-heading";
import { MonoLabel } from "@/components/ui/mono-label";
import { useBackfillMutation } from "@/lib/queries/use-backfill";
import type { BackfillReport } from "@/lib/schemas";

export function BackfillRunner({ project }: { project?: string }) {
  const [lastReport, setLastReport] = useState<BackfillReport | null>(null);
  const [dryRunSucceeded, setDryRunSucceeded] = useState(false);
  const backfill = useBackfillMutation();

  const run = (dryRun: boolean) => {
    backfill.mutate(
      { dry_run: dryRun, project },
      {
        onSuccess: (report) => {
          setLastReport(report);
          if (dryRun) setDryRunSucceeded(true);
          toast.success(
            `${dryRun ? "Dry run" : "Backfill"} — total ${report.total}: ` +
              Object.entries(report.updated_by_tier)
                .map(([k, v]) => `${k}=${v}`)
                .join(", ")
          );
        },
        onError: (err) => toast.error(err.message),
      }
    );
  };

  return (
    <Card variant="flat" className="space-y-4">
      <SerifHeading title="Lifecycle backfill" size="section" eyebrow="ONE-SHOT MIGRATION" />
      <p className="text-sm text-[var(--fg-muted)]">
        Compute tier / durability / retention_days for every existing memory. Safe. Idempotent.
      </p>

      <div className="flex gap-3">
        <Button variant="ghost" onClick={() => run(true)} loading={backfill.isPending}>
          Dry run
        </Button>
        <Button variant="ghost" onClick={() => run(false)} disabled={!dryRunSucceeded || backfill.isPending}>
          Apply
        </Button>
      </div>

      {lastReport ? (
        <div className="rounded-md border border-[var(--border)] bg-[var(--surface-0)] p-3">
          <MonoLabel>last report · {lastReport.dry_run ? "dry" : "applied"}</MonoLabel>
          <div className="mt-1 font-mono text-xs text-[var(--fg)]">
            {JSON.stringify(lastReport.updated_by_tier)}
          </div>
        </div>
      ) : null}
    </Card>
  );
}
