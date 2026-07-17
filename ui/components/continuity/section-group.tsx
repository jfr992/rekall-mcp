import type { ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { SerifHeading } from "@/components/ui/serif-heading";

type Props = {
  title: string;
  eyebrow: string;
  count: number;
  defaultOpen?: boolean;
  children: ReactNode;
};

export function SectionGroup({ title, eyebrow, count, defaultOpen = false, children }: Props) {
  return (
    <details
      open={defaultOpen}
      className="group rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)]"
    >
      <summary className="flex cursor-pointer list-none items-center gap-3 rounded-lg p-4 transition-colors hover:bg-[var(--surface-0)] [&::-webkit-details-marker]:hidden">
        <ChevronRight
          size={16}
          className="shrink-0 text-[var(--fg-muted)] transition-transform group-open:rotate-90"
        />
        <SerifHeading title={title} size="section" eyebrow={eyebrow} />
        <span className="ml-auto rounded-full border border-[var(--border)] px-2.5 py-0.5 font-mono text-xs text-[var(--fg-muted)]">
          {count}
        </span>
      </summary>
      <div className="border-t border-[var(--border)] p-4">{children}</div>
    </details>
  );
}
