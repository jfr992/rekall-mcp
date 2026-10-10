type Props = { validity: "ok" | "stale" | "withdrawn"; status?: string };

const TONE: Record<Props["validity"], string> = {
  ok: "text-[var(--fg-muted)] border-[var(--border)]",
  stale: "text-amber-400 border-amber-400/40",
  withdrawn: "text-red-400 border-red-400/40",
};

export function ValidityBadges({ validity, status }: Props) {
  return (
    <span className="flex shrink-0 items-center gap-1">
      {status === "draft" ? (
        <span className="rounded border border-[var(--border)] px-1.5 font-mono text-[10px] uppercase text-[var(--fg-dim)]">
          draft
        </span>
      ) : null}
      <span className={`rounded border px-1.5 font-mono text-[10px] uppercase ${TONE[validity]}`}>
        {validity}
      </span>
    </span>
  );
}
