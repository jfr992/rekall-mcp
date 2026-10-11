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

  return (
    <Button
      variant="ghost"
      size="sm"
      aria-label={label}
      loading={m.isPending}
      onClick={() =>
        m.mutate(
          { memoryId, disputed: !disputed },
          {
            onSuccess: () =>
              disputed
                ? toast.success("Dispute cleared")
                : toast.success("Marked disputed — suppressed from recall", {
                    action: { label: "Undo", onClick: () => m.mutate({ memoryId, disputed: false }) },
                  }),
            onError: (err) => toast.error(`${label} failed — ${err.message}`),
          },
        )
      }
    >
      {label}
    </Button>
  );
}
