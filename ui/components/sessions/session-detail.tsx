"use client";

// Extracted from app/sessions/page.tsx — unattributed caption, injected list
// and recall cards are covered by the green sessions.test.tsx cycles.
// No new behavior, presentation only.

import { MonoLabel } from "@/components/ui/mono-label";
import { MemoryRow } from "./memory-row";
import { relativeTime } from "@/lib/relative-time";
import type { SessionDetail as SessionDetailType } from "@/lib/schemas";

type Props = {
  session: SessionDetailType;
  onExpandMemory: (memoryId: string) => void;
};

export function SessionDetail({ session, onExpandMemory }: Props) {
  const unattributed = session.session_id.startsWith("unattributed:");
  // The unattributed bucket is not a real session — don't stamp its id on
  // feedback events.
  const feedbackSessionId = unattributed ? undefined : session.session_id;

  return (
    <section className="flex h-full min-h-0 min-w-0 flex-col overflow-y-auto rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-elevated)]">
      <header className="flex shrink-0 flex-col gap-1 border-b border-[var(--border)] px-5 py-4">
        <h2 className="break-all font-serif text-xl">
          {unattributed ? `Unattributed · ${session.project}` : session.session_id}
        </h2>
        <span className="flex items-baseline justify-between gap-3">
          <MonoLabel>{session.project}</MonoLabel>
          <MonoLabel>{relativeTime(session.last_at)}</MonoLabel>
        </span>
        {unattributed ? (
          <p className="text-xs text-[var(--fg-muted)]">
            Recalls that couldn&apos;t be attributed to a specific session —
            grouped per project so nothing is hidden.
          </p>
        ) : null}
      </header>

      <div className="flex flex-col gap-5 px-5 py-4">
        <div>
          <h3 className="mb-1 text-sm font-semibold text-[var(--fg)]">
            Injected ({session.injected.length})
          </h3>
          {session.injected.length === 0 ? (
            <p className="text-sm text-[var(--fg-muted)]">No injected memories.</p>
          ) : (
            <ul>
              {session.injected.map((m) => (
                <MemoryRow
                  key={m.memory_id}
                  memoryId={m.memory_id}
                  sessionId={feedbackSessionId}
                  tokenEstimate={m.token_estimate}
                  onExpand={onExpandMemory}
                />
              ))}
            </ul>
          )}
        </div>

        <div>
          <h3 className="mb-1 text-sm font-semibold text-[var(--fg)]">
            Recalls ({session.recalls.length})
          </h3>
          {session.recalls.length === 0 ? (
            <p className="text-sm text-[var(--fg-muted)]">No recalls.</p>
          ) : (
            <div className="flex flex-col gap-3">
              {session.recalls.map((recall, i) => (
                <div
                  key={`${recall.observed_at}-${i}`}
                  className="rounded-md border border-[var(--border)] p-3"
                >
                  <div className="flex items-baseline justify-between gap-3">
                    {recall.query === null ? (
                      <p className="text-xs italic text-[var(--fg-muted)]">
                        legacy event (recorded before v1.12 — no query/score data)
                      </p>
                    ) : (
                      <p className="text-sm text-[var(--fg)]">{recall.query}</p>
                    )}
                    <span className="flex shrink-0 items-center gap-2">
                      {recall.query === null ? null : (
                        <MonoLabel>
                          {recall.token_estimate === null
                            ? "—"
                            : `${recall.token_estimate} tok`}
                        </MonoLabel>
                      )}
                      <MonoLabel>{relativeTime(recall.observed_at)}</MonoLabel>
                    </span>
                  </div>
                  <ul className="mt-1">
                    {recall.memories.map((m) => (
                      <MemoryRow
                        key={m.memory_id}
                        memoryId={m.memory_id}
                        sessionId={feedbackSessionId}
                        score={recall.query === null ? undefined : m.score}
                        onExpand={onExpandMemory}
                      />
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
