"use client";

import { useEffect, useState } from "react";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { MonoLabel } from "@/components/ui/mono-label";
import type { PrunePlan } from "@/lib/schemas";

type Props = {
  open: boolean;
  plan: PrunePlan | null;
  onClose: () => void;
  onConfirm: () => void;
  loading: boolean;
};

function countByTier(plan: PrunePlan | null): Record<string, number> {
  if (!plan) return {};
  const out: Record<string, number> = {};
  for (const c of plan.candidates) {
    out[c.tier] = (out[c.tier] ?? 0) + 1;
  }
  return out;
}

export function PruneApplyDialog({ open, plan, onClose, onConfirm, loading }: Props) {
  const [focused, setFocused] = useState(false);

  useEffect(() => {
    if (open) setFocused(false);
  }, [open]);

  const count = plan?.candidates.length ?? 0;
  const byTier = countByTier(plan);

  return (
    <Dialog open={open} onClose={onClose} title={`Delete ${count} memories?`}>
      <div className="space-y-4">
        <p className="text-sm text-[var(--fg-muted)]">
          This cannot be undone. The backend will remove each memory from the store, graph, and YAML file.
        </p>
        <div className="rounded-md border border-[var(--border)] bg-[var(--surface-0)] p-3">
          <MonoLabel>by tier</MonoLabel>
          <div className="mt-1.5 flex flex-wrap gap-3 font-mono text-xs text-[var(--fg)]">
            {Object.entries(byTier).map(([tier, n]) => (
              <span key={tier}>
                {tier}: {n}
              </span>
            ))}
          </div>
        </div>
        <div className="flex justify-end gap-3">
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={loading}
            ref={(el) => {
              if (el && !focused) {
                el.focus();
                setFocused(true);
              }
            }}
          >
            Cancel
          </Button>
          <Button variant="danger" onClick={onConfirm} loading={loading}>
            Delete {count} {count === 1 ? "memory" : "memories"}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
