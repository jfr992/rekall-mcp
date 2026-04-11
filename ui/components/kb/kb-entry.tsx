"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { MonoLabel } from "@/components/ui/mono-label";
import { Badge } from "@/components/ui/badge";
import type { KbEntry as KbEntryType } from "@/lib/schemas";

type Props = {
  entry: KbEntryType;
};

export function KbEntry({ entry }: Props) {
  const [open, setOpen] = useState(false);
  return (
    <li className="border-b border-[var(--border)] last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-start gap-3 px-1 py-3 text-left transition-colors hover:bg-[var(--surface-0)]"
        aria-expanded={open}
      >
        <ChevronRight
          size={14}
          className={`mt-0.5 shrink-0 text-[var(--fg-dim)] transition-transform ${open ? "rotate-90" : ""}`}
        />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <MonoLabel>{entry.date ?? "—"}</MonoLabel>
          <p className="text-sm text-[var(--fg)]">{entry.summary}</p>
          {open && entry.content ? (
            <div className="mt-2 space-y-2 rounded-md border border-[var(--border)] bg-[var(--surface-0)] p-3">
              <p className="text-sm leading-relaxed text-[var(--fg)]">{entry.content}</p>
              <div className="flex items-center gap-2">
                {entry.tier ? <Badge kind="tier" value={entry.tier} /> : null}
                {entry.type ? <Badge kind="type" value={entry.type} /> : null}
              </div>
            </div>
          ) : null}
        </div>
      </button>
    </li>
  );
}
