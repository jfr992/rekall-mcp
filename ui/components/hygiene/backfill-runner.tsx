"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { SerifHeading } from "@/components/ui/serif-heading";
import { MonoLabel } from "@/components/ui/mono-label";
import { useBackfillMutation } from "@/lib/queries/use-backfill";
import type { BackfillReport } from "@/lib/schemas";

const MAX_CHANGED = 20;

const summarize = (r: BackfillReport) => {
  const t = r.tier_changes ?? {};
  return `${t.promoted ?? 0} promoted · ${t.demoted ?? 0} demoted`;
};

export function BackfillRunner({ project }: { project?: string }) {
  const [lastReport, setLastReport] = useState<BackfillReport | null>(null);
  const [dryRunChanged, setDryRunChanged] = useState<number | null>(null);
  const backfill = useBackfillMutation();

  const currentProject = useRef(project);

  useEffect(() => {
    currentProject.current = project;
    setDryRunChanged(null);
  }, [project]);

  const run = (dryRun: boolean) => {
    backfill.mutate(
      { dry_run: dryRun, project },
      {
        onSuccess: (report) => {
          setLastReport(report);
          if (dryRun && currentProject.current === project) setDryRunChanged(report.changed?.length ?? 0);
          toast.success(`${dryRun ? "Dry run" : "Backfill"} — ${summarize(report)} of ${report.total}`);
        },
        onError: (err) => toast.error(err.message),
      }
    );
  };

  const apply = () => {
    const scope = project ? ` to ${project}` : "";
    if (!window.confirm(`Apply lifecycle backfill${scope}? The dry run would change ${dryRunChanged} memories.`)) return;
    run(false);
  };

  return (
    <Card variant="flat" className="flex h-full flex-col gap-4">
      <div>
        <SerifHeading title="Lifecycle backfill" size="section" eyebrow="ONE-SHOT MIGRATION" />
        <p className="mt-1.5 text-sm text-[var(--fg-muted)]">
          Compute tier / durability / retention_days for every existing memory. Safe. Idempotent.
        </p>
      </div>

      <div className="mt-auto flex gap-3 pt-1">
        <Button variant="ghost" onClick={() => run(true)} loading={backfill.isPending}>
          Dry run
        </Button>
        <Button variant="ghost" onClick={apply} disabled={dryRunChanged === null || backfill.isPending}>
          Apply
        </Button>
      </div>

      {lastReport ? (
        <div className="rounded-md border border-[var(--border)] bg-[var(--surface-0)] p-3">
          <MonoLabel>last report · {lastReport.dry_run ? "dry" : "applied"}</MonoLabel>
          <div className="mt-1 font-mono text-xs text-[var(--fg)]">
            {summarize(lastReport)}
          </div>
          {lastReport.changed?.length ? (
            <ul className="mt-2 space-y-0.5 font-mono text-[11px] text-[var(--fg-muted)]">
              {lastReport.changed.slice(0, MAX_CHANGED).map((c) => (
                <li key={c.memory_id}>{c.memory_id}: {c.from ?? "—"} → {c.to}</li>
              ))}
              {lastReport.changed.length > MAX_CHANGED ? <li>and {lastReport.changed.length - MAX_CHANGED} more</li> : null}
            </ul>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}
