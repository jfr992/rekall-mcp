"use client";

// Extracted from app/sessions/page.tsx — expand button, score/token labels and
// optimistic feedback buttons are covered by the green sessions.test.tsx
// cycles. No new behavior, presentation only.

import { useState } from "react";
import { toast } from "sonner";
import { MonoLabel } from "@/components/ui/mono-label";
import { useFeedbackMutation } from "@/lib/queries/use-feedback";
import type { FeedbackVerdict } from "@/lib/api/feedback";

const VERDICTS: FeedbackVerdict[] = ["useful", "wrong", "stale"];

type Props = {
  memoryId: string;
  sessionId?: string;
  score?: number;
  tokenEstimate?: number | null;
  onExpand: (memoryId: string) => void;
};

export function MemoryRow({ memoryId, sessionId, score, tokenEstimate, onExpand }: Props) {
  const [verdict, setVerdict] = useState<FeedbackVerdict | null>(null);
  const feedback = useFeedbackMutation();

  function give(next: FeedbackVerdict) {
    const prev = verdict;
    setVerdict(next); // optimistic — reverted onError
    feedback.mutate(
      { memoryId, verdict: next, sessionId },
      {
        onError: (err) => {
          setVerdict(prev);
          toast.error(`Feedback failed: ${err.message}`);
        },
      }
    );
  }

  return (
    <li className="flex flex-wrap items-center justify-between gap-2 rounded-[7px] border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-2 transition-colors hover:border-[rgba(45,212,160,0.4)]">
      <button
        type="button"
        aria-label={`Expand ${memoryId}`}
        onClick={() => onExpand(memoryId)}
        className="break-all text-left font-mono text-xs text-[var(--fg)] underline-offset-2 hover:underline"
      >
        {memoryId}
      </button>
      <span className="flex shrink-0 items-center gap-2">
        {score !== undefined ? <MonoLabel>{score.toFixed(2)}</MonoLabel> : null}
        {tokenEstimate !== undefined ? (
          <MonoLabel>{tokenEstimate === null ? "—" : `${tokenEstimate} tok`}</MonoLabel>
        ) : null}
        {VERDICTS.map((v) => (
          <button
            key={v}
            type="button"
            aria-label={`Mark ${memoryId} ${v}`}
            aria-pressed={verdict === v}
            onClick={() => give(v)}
            className={`rounded px-1.5 py-0.5 font-mono text-[11px] transition-colors ${
              verdict === v
                ? "bg-[var(--accent-primary)] text-[var(--bg-deep)]"
                : "border border-[var(--border)] text-[var(--fg-muted)] hover:text-[var(--fg)]"
            }`}
          >
            {v}
          </button>
        ))}
      </span>
    </li>
  );
}
