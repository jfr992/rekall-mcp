import type { HTMLAttributes, ReactNode } from "react";

type Props = HTMLAttributes<HTMLDivElement> & {
  eyebrow?: ReactNode;
  title: ReactNode;
  size?: "page" | "section";
};

export function SerifHeading({ eyebrow, title, size = "page", className = "", ...rest }: Props) {
  const titleClass =
    size === "page" ? "font-serif text-[clamp(2rem,3.5vw,2.75rem)] leading-[1.1]" : "font-serif text-2xl";
  return (
    <div className={`flex flex-col gap-1.5 ${className}`} {...rest}>
      {eyebrow ? (
        <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--accent-primary)]">
          {eyebrow}
        </span>
      ) : null}
      <h1 className={titleClass}>{title}</h1>
    </div>
  );
}
