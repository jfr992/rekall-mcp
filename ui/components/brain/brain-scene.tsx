import type { ReactNode } from "react";

export function BrainScene({ children }: { children: ReactNode }) {
  return (
    <div className="relative h-full w-full overflow-hidden">
      <div className="aurora-bg" aria-hidden />
      <div className="absolute inset-0 starfield" aria-hidden />
      <div className="relative h-full w-full">{children}</div>
    </div>
  );
}
