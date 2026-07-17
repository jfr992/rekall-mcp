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
      <header className="flex shrink-0 flex-col gap-1.5 border-b border-[var(--border)] px-5 py-4">
        <h2 className="break-all font-mono text-[15px] font-medium text-[var(--fg)]">
          {unattributed ? `Unattributed · ${session.project}` : session.session_id}
        </h2>
        <span className="flex items-baseline gap-3.5 font-mono text-[10.5px] text-[var(--fg-dim)]">
          <span className="text-[var(--accent-bright)]">{session.project}</span>
          <span>{relativeTime(session.last_at)}</span>
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
          {/* Kicker keeps the literal "injected (N)" so the sessions pin stays green */}
          <h3 className="mb-2 font-mono text-[11px] font-medium uppercase tracking-[0.16em] text-[var(--fg-dim)]">
            Injected ({session.injected.length}) · at start
          </h3>
          {session.injected.length === 0 ? (
            <p className="text-sm text-[var(--fg-muted)]">No injected memories.</p>
          ) : (
            <ul className="flex flex-col gap-1.5">
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
          <h3 className="mb-2 font-mono text-[11px] font-medium uppercase tracking-[0.16em] text-[var(--fg-dim)]">
            Recalls ({session.recalls.length})
          </h3>
          {session.recalls.length === 0 ? (
            <p className="text-sm text-[var(--fg-muted)]">No recalls.</p>
          ) : (
            <div className="flex flex-col gap-3">
              {session.recalls.map((recall, i) => (
                <div
                  key={`${recall.observed_at}-${i}`}
                  className="rounded-[9px] border border-[var(--border)] bg-[var(--bg-base)] px-3.5 py-3"
                >
                  <div className="flex items-baseline justify-between gap-3">
                    {recall.query === null ? (
                      <p className="text-xs italic text-[var(--fg-muted)]">
                        legacy event (recorded before v1.12 — no query/score data)
                      </p>
                    ) : (
                      <p className="text-sm text-[var(--fg)]">&ldquo;{recall.query}&rdquo;</p>
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
                  <ul className="mt-2 flex flex-col gap-1.5">
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
