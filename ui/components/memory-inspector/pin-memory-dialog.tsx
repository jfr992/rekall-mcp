"use client";

import { toast } from "sonner";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { usePinMemory } from "@/lib/queries/use-pin-memory";

type Props = {
  memoryId: string;
  content: string;
  pinned: boolean;
  onCancel: () => void;
  onDone: () => void;
};

export function PinMemoryDialog({ memoryId, content, pinned, onCancel, onDone }: Props) {
  const pin = usePinMemory();
  const title = pinned
    ? "Remove identity pin from this memory?"
    : "Promote this memory to identity?";

  return (
    <Dialog open onClose={onCancel} title={title}>
      <p className="rounded-md border border-[var(--border)] bg-[var(--surface-0)] p-3 text-sm text-[var(--fg)]">
        {content}
      </p>
      <div className="mt-4 flex justify-end gap-3">
        <Button variant="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          variant="primary"
          size="sm"
          aria-label={pinned ? "Confirm remove identity pin" : "Confirm promote to identity"}
          loading={pin.isPending}
          onClick={() =>
            pin.mutate(
              { memoryId, pinned: !pinned },
              {
                onSuccess: onDone,
                onError: (err) => toast.error(`Pin failed — ${err.message}`),
              },
            )
          }
        >
          {pinned ? "Remove pin" : "Promote to identity"}
        </Button>
      </div>
    </Dialog>
  );
}
