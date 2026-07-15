"use client";

import { MonoLabel } from "@/components/ui/mono-label";
import { relativeTime } from "@/lib/relative-time";
import type { SessionRow } from "@/lib/schemas";

type Props = {
  sessions: SessionRow[];
  selectedId: string | null;
  onSelect: (sessionId: string) => void;
};

export function SessionList({ sessions, selectedId, onSelect }: Props) {
  return (
    <section className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-elevated)]">
      <header className="flex shrink-0 items-baseline justify-between gap-3 border-b border-[var(--border)] px-5 py-4">
        <h2 className="font-serif text-xl">Sessions</h2>
        <MonoLabel>{sessions.length}</MonoLabel>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {sessions.length === 0 ? (
          <p className="px-5 py-4 text-sm text-[var(--fg-muted)]">
            No sessions in the event window.
          </p>
        ) : (
          <ul>
            {sessions.map((s) => {
              const unattributed = s.session_id.startsWith("unattributed:");
              const active = selectedId === s.session_id;
              return (
                <li key={s.session_id} className="border-b border-[var(--border)] last:border-b-0">
                  <button
                    type="button"
                    aria-pressed={active}
                    onClick={() => onSelect(s.session_id)}
                    className={`flex w-full flex-col gap-1 px-5 py-3 text-left transition-colors ${
                      active
                        ? "bg-[var(--surface-1)] shadow-[inset_2px_0_0_var(--accent-primary)]"
                        : "hover:bg-[var(--surface-0)]"
                    }`}
                  >
                    <span className="break-all font-mono text-xs text-[var(--fg)]">
                      {unattributed ? `Unattributed · ${s.project}` : s.session_id}
                    </span>
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="text-xs text-[var(--fg-muted)]">
                        {s.totals.recalls} recalls · {s.totals.injected} injected ·{" "}
                        {s.totals.tokens} tok
                      </span>
                      <MonoLabel>{relativeTime(s.last_at)}</MonoLabel>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
