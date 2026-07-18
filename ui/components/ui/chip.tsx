import type { ReactNode } from "react";

type Props = {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
  className?: string;
};

// Filter chip with the kb tab-pill active treatment — shared by the kb
// recency rail and the stream range row so pressed state reads the same way.
export function Chip({ active, onClick, children, className = "" }: Props) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`cursor-pointer rounded px-1.5 py-0.5 text-left text-xs transition-colors ${
        active
          ? "bg-[rgba(45,212,160,0.14)] font-medium text-[var(--accent-primary)]"
          : "text-[var(--fg-muted)] hover:text-[var(--fg)]"
      } ${className}`}
    >
      {children}
    </button>
  );
}
