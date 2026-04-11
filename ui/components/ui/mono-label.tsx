import type { HTMLAttributes } from "react";

export function MonoLabel({ className = "", ...rest }: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={`font-mono text-[11px] uppercase tracking-[0.08em] text-[var(--fg-muted)] ${className}`}
      {...rest}
    />
  );
}
