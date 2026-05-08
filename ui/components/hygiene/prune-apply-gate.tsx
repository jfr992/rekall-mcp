"use client";

import { useState } from "react";
import { AlertTriangle, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MonoLabel } from "@/components/ui/mono-label";

type Props = {
  planId: string;
  candidateCount: number;
  expired: boolean;
  loading: boolean;
  onRequestApply: () => void;
};

export function PruneApplyGate({ planId, candidateCount, expired, loading, onRequestApply }: Props) {
  const [typed, setTyped] = useState("");
  const primed = typed === planId && !expired && candidateCount > 0;

  if (candidateCount === 0) return null;

  return (
    <div className="space-y-4 rounded-md border border-[var(--accent-danger)]/40 bg-[var(--accent-danger)]/10 p-4">
      <div className="flex items-start gap-3">
        <ShieldAlert size={18} className="mt-0.5 shrink-0 text-[var(--accent-danger)]" />
        <div>
          <p className="font-serif text-base text-[var(--fg)]">
            {candidateCount} {candidateCount === 1 ? "memory" : "memories"} will be permanently deleted.
          </p>
          <p className="mt-1 text-xs text-[var(--fg-muted)]">
            Type the full plan id below to confirm. This is deliberately paranoid — paste-only
            muscle memory is not allowed.
          </p>
        </div>
      </div>

      <label className="block">
        <MonoLabel>type the plan id to confirm</MonoLabel>
        <input
          type="text"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          placeholder={`${planId.slice(0, 4)}…`}
          spellCheck={false}
          autoComplete="off"
          disabled={expired || loading}
          className="mt-1 w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 font-mono text-sm text-[var(--fg)] placeholder:text-[var(--fg-dim)] focus:border-[var(--accent-danger)] focus:outline-none disabled:opacity-50"
          aria-describedby="prune-danger"
        />
      </label>

      {typed && !primed && !expired ? (
        <p className="flex items-center gap-1.5 text-xs text-[var(--accent-warning)]">
          <AlertTriangle size={12} />
          does not match plan id
        </p>
      ) : null}

      <div className="flex justify-end">
        <Button
          variant={primed ? "danger" : "ghost"}
          onClick={onRequestApply}
          disabled={!primed || loading}
          loading={loading}
        >
          {expired ? "Plan expired" : loading ? "Deleting" : `Apply · delete ${candidateCount}`}
        </Button>
      </div>
    </div>
  );
}
