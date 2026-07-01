"use client";

import { useState } from "react";
import { Maximize2 } from "lucide-react";
import { Dialog } from "@/components/ui/dialog";
import { MonoLabel } from "@/components/ui/mono-label";
import { Badge } from "@/components/ui/badge";
import type { KbEntry as KbEntryType } from "@/lib/schemas";

type Props = {
  entry: KbEntryType;
};

export function KbEntry({ entry }: Props) {
  const [open, setOpen] = useState(false);
  const full = entry.content ?? entry.summary;

  return (
    <li className="border-b border-[var(--border)] last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="group flex w-full items-start gap-3 px-1 py-3 text-left transition-colors hover:bg-[var(--surface-0)]"
      >
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <MonoLabel>{entry.date ?? "—"}</MonoLabel>
          <p className="line-clamp-2 text-sm text-[var(--fg)]">{entry.summary}</p>
        </div>
        <Maximize2
          size={13}
          className="mt-0.5 shrink-0 text-[var(--fg-muted)] opacity-0 transition-opacity group-hover:opacity-100"
        />
      </button>

      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title={<span className="text-lg">{entry.date ?? "Memory"}</span>}
      >
        <div className="space-y-4">
          {entry.tier || entry.type ? (
            <div className="flex flex-wrap items-center gap-2">
              {entry.type ? <Badge kind="type" value={entry.type} /> : null}
              {entry.tier ? <Badge kind="tier" value={entry.tier} /> : null}
            </div>
          ) : null}
          <p className="max-h-[60vh] overflow-auto whitespace-pre-wrap text-[15px] leading-relaxed text-[var(--fg)]">
            {full}
          </p>
          {entry.memory_id ? (
            <MonoLabel className="block break-all">{entry.memory_id}</MonoLabel>
          ) : null}
        </div>
      </Dialog>
    </li>
  );
}
