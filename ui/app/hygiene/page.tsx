"use client";

import { useState } from "react";
import { toast } from "sonner";
import { SerifHeading } from "@/components/ui/serif-heading";
import { Empty } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { PressureGauges } from "@/components/hygiene/pressure-gauges";
import { PressureExplainer } from "@/components/hygiene/pressure-explainer";
import { FlaggedPanel } from "@/components/hygiene/flagged-panel";
import { MemoryInspector } from "@/components/memory-inspector/memory-inspector";
import { PruneBuilder } from "@/components/hygiene/prune-builder";
import { PrunePlanReview } from "@/components/hygiene/prune-plan-review";
import { PruneApplyGate } from "@/components/hygiene/prune-apply-gate";
import { PruneApplyDialog } from "@/components/hygiene/prune-apply-dialog";
import { BackfillRunner } from "@/components/hygiene/backfill-runner";
import { usePressure } from "@/lib/queries/use-pressure";
import { usePrunePlanMutation, usePruneApplyMutation } from "@/lib/queries/use-prune";
import { useProjectStore } from "@/lib/project-store";
import { useMemoryDetail } from "@/lib/queries/use-memory-detail";
import { scopedTitle } from "@/lib/scoped-title";
import type { PrunePlan } from "@/lib/schemas";

export default function HygienePage() {
  const project = useProjectStore((s) => s.project);
  const pressure = usePressure(project);
  const planMutation = usePrunePlanMutation();
  const applyMutation = usePruneApplyMutation();

  const [plan, setPlan] = useState<PrunePlan | null>(null);
  const [inspecting, setInspecting] = useState<string | null>(null);
  const detail = useMemoryDetail(inspecting);
  const [dialogOpen, setDialogOpen] = useState(false);

  const handleBuild = () => {
    planMutation.mutate(
      { project },
      {
        onSuccess: (result) => {
          setPlan(result);
          toast(
            result.candidates.length === 0
              ? "Nothing to prune."
              : `Plan ${result.plan_id.slice(0, 8)}… built. ${result.candidates.length} candidates.`
          );
        },
        onError: (err) => toast.error(err.message),
      }
    );
  };

  const handleApply = () => {
    if (!plan) return;
    applyMutation.mutate(
      { planId: plan.plan_id, confirm: plan.plan_id },
      {
        onSuccess: (res) => {
          setDialogOpen(false);
          setPlan(null);
          toast.success(`Deleted ${res.deleted.length}. Skipped ${res.skipped.length}.`);
        },
        onError: (err) => toast.error(err.message),
      }
    );
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <SerifHeading eyebrow="PRESSURE · PRUNE · BACKFILL" title={scopedTitle("Memory Hygiene", project)} />

      <section className="space-y-3">
        {pressure.isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : pressure.data ? (
          <>
            <PressureGauges data={pressure.data} />
            <PressureExplainer data={pressure.data} />
            <FlaggedPanel flagged={pressure.data.flagged} onSelect={setInspecting} />
          </>
        ) : (
          <Empty title="Could not load pressure" />
        )}
      </section>

      {/* Stable children order keeps BackfillRunner mounted (dry-run gate state) */}
      <section className="grid grid-cols-1 gap-3.5 md:grid-cols-2">
        <div className={plan === null ? "" : "md:col-span-2"}>
          {plan === null ? (
            <PruneBuilder onBuild={handleBuild} loading={planMutation.isPending} />
          ) : (
            <PrunePlanReview plan={plan}>
              {({ expired }) => (
                <PruneApplyGate
                  planId={plan.plan_id}
                  candidateCount={plan.candidates.length}
                  expired={expired}
                  loading={applyMutation.isPending}
                  onRequestApply={() => setDialogOpen(true)}
                />
              )}
            </PrunePlanReview>
          )}
        </div>
        <BackfillRunner project={project} />
      </section>

      <PruneApplyDialog
        open={dialogOpen}
        plan={plan}
        loading={applyMutation.isPending}
        onClose={() => setDialogOpen(false)}
        onConfirm={handleApply}
      />

      <MemoryInspector
        open={inspecting !== null}
        detail={detail.data}
        isLoading={detail.isLoading}
        currentProject={project}
        onClose={() => setInspecting(null)}
        onSelectMemory={setInspecting}
      />
    </div>
  );
}
