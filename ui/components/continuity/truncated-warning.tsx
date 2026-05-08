import { AlertTriangle } from "lucide-react";

export function TruncatedWarning({ truncated }: { truncated: boolean }) {
  if (!truncated) return null;
  return (
    <div className="flex items-start gap-3 rounded-md border border-[var(--accent-warning)]/40 bg-[var(--accent-warning)]/10 p-4">
      <AlertTriangle size={18} className="mt-0.5 shrink-0 text-[var(--accent-warning)]" />
      <div>
        <p className="text-sm font-medium text-[var(--fg)]">Showing recent window</p>
        <p className="mt-1 text-xs text-[var(--fg-muted)]">
          This project exceeds the bounded scroll cap. You are seeing the most recent slice, not
          the full set.
        </p>
      </div>
    </div>
  );
}
