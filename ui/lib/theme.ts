// Typed references to CSS variables, for inline styles and JS consumers
// (react-force-graph-2d needs concrete color strings).
// Keep in sync with the :root tokens in app/globals.css.

export const tokens = {
  bg: {
    deep: "#0a100e",
    base: "#0c1310",
    elevated: "#0f1714",
    raised: "#141e1a",
    frost: "rgba(10, 16, 14, 0.92)",
  },
  fg: {
    primary: "#e6efe9",
    soft: "#bccac2",
    muted: "#84988d",
    dim: "#75897f",
    // Large/decorative only — 3.75:1 on bg.deep fails AA for body text
    faint: "#5f7269",
  },
  accent: {
    primary: "#2dd4a0",
    bright: "#7fe8c3",
    secondary: "#a78bfa",
    danger: "#f87171",
    warning: "#f2c14e",
    success: "#a3e635",
  },
  // Tier remap for the dark-green palette (old → new):
  //   identity  #fbbf24 amber  → #a78bfa violet (mockup ladder)
  //   semantic  #a78bfa violet → #2dd4a0 mint   (primary accent)
  //   episodic  #60a5fa blue   → #38bdf8 sky    (mockup ladder)
  //   working   #94a3b8 slate  → #75897f moss   (AA-safe; mockup's #5f7269 fails 4.5:1)
  tier: {
    identity: "#a78bfa",
    semantic: "#2dd4a0",
    episodic: "#38bdf8",
    working: "#75897f",
  },
  // Design-source type colors; session/summary are design-consistent muted
  // picks (summary ties to the consolidation violet family).
  type: {
    preference: "#f2c14e",
    decision: "#2dd4a0",
    requirement: "#fb7185",
    learning: "#a3e635",
    fact: "#38bdf8",
    note: "#8fa39a",
    session: "#7fb4d8",
    summary: "#c4b5fd",
  },
  border: {
    subtle: "rgba(125, 200, 170, 0.1)",
    strong: "rgba(125, 200, 170, 0.25)",
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
