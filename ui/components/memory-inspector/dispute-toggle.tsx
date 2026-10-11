"use client";

import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useDisputeMemory } from "@/lib/queries/use-dispute-memory";

type Props = {
  memoryId: string;
  disputed: boolean;
};

export function DisputeToggle({ memoryId, disputed }: Props) {
  const m = useDisputeMemory();
  const label = disputed ? "Un-dispute" : "Dispute";

  const callbacks = (l: string, onDone: () => void) => ({
    onSuccess: onDone,
    onError: (err: Error) => toast.error(`${l} failed — ${err.message}`),
  });
  const clear = () => toast.success("Dispute cleared");
  const undo = () => m.mutate({ memoryId, disputed: false }, callbacks("Undo", clear));

  return (
    <Button
      variant="ghost"
      size="sm"
      aria-label={label}
      loading={m.isPending}
      onClick={() =>
        m.mutate(
          { memoryId, disputed: !disputed },
          callbacks(label, () =>
            disputed
              ? clear()
              : toast.success("Marked disputed — suppressed from recall", {
                  action: { label: "Undo", onClick: undo },
                }),
          ),
        )
      }
    >
      {label}
    </Button>
  );
}
