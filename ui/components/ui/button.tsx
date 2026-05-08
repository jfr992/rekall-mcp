import { forwardRef, type ButtonHTMLAttributes } from "react";
import { Loader2 } from "lucide-react";

type Variant = "primary" | "ghost" | "danger" | "secondary";
type Size = "sm" | "md" | "lg";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
};

const variantClass: Record<Variant, string> = {
  primary:
    "bg-[var(--accent-primary)] text-[var(--bg-deep)] hover:brightness-110 focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] focus:ring-offset-2 focus:ring-offset-[var(--bg-deep)]",
  ghost:
    "border border-[var(--border)] text-[var(--fg)] hover:bg-[var(--surface-1)] focus:outline-none focus:ring-2 focus:ring-[var(--border-strong)]",
  danger:
    "bg-[var(--accent-danger)] text-[var(--bg-deep)] hover:brightness-110 focus:outline-none focus:ring-2 focus:ring-[var(--accent-danger)] focus:ring-offset-2 focus:ring-offset-[var(--bg-deep)] shadow-[0_0_24px_rgba(248,113,113,0.35)]",
  secondary:
    "bg-[var(--surface-1)] text-[var(--fg)] hover:bg-[var(--surface-2)] focus:outline-none focus:ring-2 focus:ring-[var(--border-strong)]",
};

const sizeClass: Record<Size, string> = {
  sm: "h-8 px-3 text-sm rounded-md",
  md: "h-10 px-4 text-sm rounded-md",
  lg: "h-12 px-6 text-base rounded-lg",
};

export const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  { variant = "primary", size = "md", loading, disabled, children, className = "", ...rest },
  ref
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center gap-2 font-medium transition-[background,transform,opacity,box-shadow] duration-[150ms] disabled:opacity-40 disabled:cursor-not-allowed ${variantClass[variant]} ${sizeClass[size]} ${className}`}
      {...rest}
    >
      {loading ? <Loader2 className="animate-spin" size={16} /> : null}
      {children}
    </button>
  );
});
