export function KbEmpty({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center gap-1 py-8 text-center">
      <span className="font-serif text-3xl text-[var(--fg-dim)]">—</span>
      <p className="text-xs text-[var(--fg-dim)]">no {label} yet</p>
    </div>
  );
}
