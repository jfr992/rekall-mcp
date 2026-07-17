"use client";

import { toast } from "sonner";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useDeleteMemory } from "@/lib/queries/use-delete-memory";

type Props = {
  memoryId: string;
  content: string;
  onCancel: () => void;
  onDone: () => void;
};

export function DeleteMemoryDialog({ memoryId, content, onCancel, onDone }: Props) {
  const deletion = useDeleteMemory();

  return (
    <Dialog open onClose={onCancel} title="Delete this memory?">
      <p className="rounded-md border border-[var(--border)] bg-[var(--surface-0)] p-3 text-sm text-[var(--fg)]">
        {content}
      </p>
      <div className="mt-4 flex justify-end gap-3">
        <Button variant="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          variant="danger"
          size="sm"
          aria-label="Confirm delete"
          loading={deletion.isPending}
          onClick={() =>
            deletion.mutate(
              { memoryId },
              {
                onSuccess: onDone,
                onError: (err) => toast.error(`Delete failed — ${err.message}`),
              },
            )
          }
        >
          Delete memory
        </Button>
      </div>
    </Dialog>
  );
}
