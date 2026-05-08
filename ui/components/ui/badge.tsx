import type { HTMLAttributes } from "react";
import { tierColor, typeColor } from "@/lib/theme";

type Kind = "type" | "tier";

type Props = HTMLAttributes<HTMLSpanElement> & {
  kind: Kind;
  value: string;
};

export function Badge({ kind, value, className = "", ...rest }: Props) {
  const color = kind === "type" ? typeColor(value) : tierColor(value);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium uppercase tracking-[0.08em] ${className}`}
      style={{
        color,
        borderColor: `${color}55`,
        backgroundColor: `${color}12`,
      }}
      {...rest}
    >
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ background: color, boxShadow: `0 0 8px ${color}` }}
      />
      {value}
    </span>
  );
}
