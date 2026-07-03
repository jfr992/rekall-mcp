"use client";

import { ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { MonoLabel } from "@/components/ui/mono-label";

type Props = {
  memoryId: string;
  content: string;
  type?: string;
  tier?: string;
  date?: string;
  onSelect: (memoryId: string) => void;
};

export function MemoryRow({ memoryId, content, type, tier, date, onSelect }: Props) {
  return (
    <button
      type="button"
      aria-haspopup="dialog"
      onClick={() => onSelect(memoryId)}
      className="flex w-full items-center gap-3 rounded-md border border-[var(--border)] bg-[var(--surface-0)] px-3 py-2 text-left transition-colors hover:border-[var(--fg-muted)]/40 hover:bg-[var(--bg-elevated)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-primary)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg)]"
    >
      {type ? <Badge kind="type" value={type} /> : null}
      {tier && tier !== "working" ? <Badge kind="tier" value={tier} /> : null}
      <span className="min-w-0 flex-1 truncate font-serif text-sm text-[var(--fg)]">
        {content}
      </span>
      <MonoLabel>{date ?? ""}</MonoLabel>
      <ChevronRight size={14} className="shrink-0 text-[var(--fg-muted)]" />
    </button>
  );
}
