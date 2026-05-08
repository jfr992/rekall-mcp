import type { ReactNode } from "react";

type Props = {
  title: string;
  hint?: ReactNode;
};

export function Empty({ title, hint }: Props) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
      <p className="font-serif text-lg text-[var(--fg-muted)]">{title}</p>
      {hint ? <p className="text-sm text-[var(--fg-dim)]">{hint}</p> : null}
    </div>
  );
}
