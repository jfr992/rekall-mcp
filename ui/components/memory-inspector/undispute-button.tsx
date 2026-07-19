"use client";

import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useDisputeMemory } from "@/lib/queries/use-dispute-memory";

type Props = {
  memoryId: string;
};

// Minimal v1 resolution affordance (PLAN.md T5) — single click, no confirm
// dialog. Unlike delete/pin this only clears a review flag, it isn't
// destructive or identity-elevating.
export function UndisputeButton({ memoryId }: Props) {
  const undispute = useDisputeMemory();

  return (
    <Button
      variant="ghost"
      size="sm"
      aria-label="Un-dispute"
      loading={undispute.isPending}
      onClick={() =>
        undispute.mutate(
          { memoryId, disputed: false },
          { onError: (err) => toast.error(`Un-dispute failed — ${err.message}`) },
        )
      }
    >
      Un-dispute
    </Button>
  );
}
