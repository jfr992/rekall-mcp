"use client";

import { useQuery } from "@tanstack/react-query";
import { Drawer } from "@/components/ui/drawer";
import { Badge } from "@/components/ui/badge";
import { MonoLabel } from "@/components/ui/mono-label";
import { getByEntity } from "@/lib/api/by-entity";

type Props = {
  entity: string;
  project: string;
  onClose: () => void;
  onSelectMemory: (memoryId: string) => void;
};

export function EntityBacklinks({ entity, project, onClose, onSelectMemory }: Props) {
  const { data, isFetched } = useQuery({
    queryKey: ["by-entity", project, entity],
    queryFn: () => getByEntity(entity, project),
    staleTime: 30_000,
  });
  const memories = data?.memories ?? [];

  return (
    <Drawer
      open
      onClose={onClose}
      ariaLabel={`Memories mentioning ${entity}`}
      title={
        <div className="flex flex-col gap-1">
          <span className="text-sm font-semibold text-[var(--fg)]">Backlinks</span>
          <MonoLabel>{entity}</MonoLabel>
        </div>
      }
    >
      {memories.length === 0 && isFetched ? (
        <p className="text-sm text-[var(--fg-muted)]">
          No other memories mention {entity}.
        </p>
      ) : (
        <ul className="space-y-1">
          {memories.map((m) => (
            <li key={m.memory_id}>
              <button
                type="button"
                onClick={() => onSelectMemory(m.memory_id)}
                className="flex w-full items-center gap-3 rounded-md border border-transparent px-3 py-2 text-left hover:border-[var(--border)] hover:bg-[var(--surface-1)]"
              >
                {m.type ? <Badge kind="type" value={m.type} /> : null}
                <span className="min-w-0 flex-1 truncate text-sm text-[var(--fg)]">
                  {m.content}
                </span>
                {m.date ? <MonoLabel>{m.date}</MonoLabel> : null}
              </button>
            </li>
          ))}
        </ul>
      )}
    </Drawer>
  );
}
