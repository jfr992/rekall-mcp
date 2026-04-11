// Typed references to CSS variables, for inline styles and JS consumers
// (react-force-graph-2d needs concrete color strings).

export const tokens = {
  bg: {
    deep: "#020617",
    base: "#0a0f1f",
    elevated: "#0f172a",
    frost: "rgba(15, 23, 42, 0.72)",
  },
  fg: {
    primary: "#f1f5f9",
    muted: "#94a3b8",
    dim: "#64748b",
  },
  accent: {
    primary: "#60a5fa",
    secondary: "#a78bfa",
    danger: "#f87171",
    warning: "#f59e0b",
    success: "#34d399",
  },
  tier: {
    identity: "#fbbf24",
    semantic: "#a78bfa",
    episodic: "#60a5fa",
    working: "#94a3b8",
  },
  type: {
    fact: "#60a5fa",
    decision: "#f59e0b",
    preference: "#c084fc",
    learning: "#34d399",
    requirement: "#f87171",
    note: "#94a3b8",
    session: "#cbd5e1",
  },
  border: {
    subtle: "rgba(148, 163, 184, 0.12)",
    strong: "rgba(148, 163, 184, 0.24)",
  },
} as const;

export type Tier = keyof typeof tokens.tier;
export type MemoryType = keyof typeof tokens.type;

export function tierColor(tier: string | undefined): string {
  if (!tier) return tokens.tier.working;
  return (tokens.tier as Record<string, string>)[tier] ?? tokens.tier.working;
}

export function typeColor(type: string | undefined): string {
  if (!type) return tokens.type.note;
  return (tokens.type as Record<string, string>)[type] ?? tokens.type.note;
}
