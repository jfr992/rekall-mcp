import type { HTMLAttributes } from "react";

type Variant = "flat" | "elevated" | "glass";

type Props = HTMLAttributes<HTMLDivElement> & {
  variant?: Variant;
};

const variantClass: Record<Variant, string> = {
  flat: "bg-[var(--bg-elevated)] border border-[var(--border)]",
  elevated: "bg-[var(--bg-elevated)] border border-[var(--border)] shadow-[0_20px_50px_rgba(0,0,0,0.35)]",
  glass:
    "bg-[var(--bg-frost)] border border-[var(--border)] backdrop-blur-[18px] backdrop-saturate-150 shadow-[0_20px_50px_rgba(0,0,0,0.45)]",
};

export function Card({ variant = "flat", className = "", ...rest }: Props) {
  return <div className={`rounded-[var(--radius-lg)] p-5 ${variantClass[variant]} ${className}`} {...rest} />;
}
