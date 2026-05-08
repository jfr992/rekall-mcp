# Memory Cockpit UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `ui/` as a Brain Observatory cockpit for Memento MCP — four Next.js App Router routes (Brain / KB / Continuity / Hygiene) wired to the hardened backend endpoints, with a force-directed graph, typed KB slices, continuity console, and a safe two-step prune flow.

**Architecture:** Next.js 15 App Router with a shared `CockpitShell` around four client-component routes, all data fetched via TanStack Query v5 against the 7 new backend endpoints. Zod schemas validate every response at the client boundary. One design-system (CSS variables + Tailwind v4 + self-hosted IBM Plex Serif / Inter / JetBrains Mono). The Hygiene surface owns the prune plan/apply flow with a typed-plan-id gate layered on top of the backend's plan-id confirmation.

**Tech Stack:** Next.js 15 App Router, React 19, TypeScript 5.9, Tailwind v4, TanStack Query v5, `react-force-graph-2d`, Zod, `lucide-react`, `sonner`, `framer-motion`, `zustand`, Vitest + Testing Library + jsdom.

**Spec:** `docs/superpowers/specs/2026-04-10-memory-cockpit-ui-design.md`

**Depends on:** `p1-api-green` tag — backend hardening must be complete.

---

## Working rules

- Stay on `feature/agent-memory-os`. No new branches, no push to remote.
- Every commit uses the trailer `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>`.
- All UI work lives under `ui/`. The backend is not touched by this plan.
- Run UI commands from inside `ui/`: `cd ui && npm run dev`, `cd ui && npm test`, etc.
- Backend must be running on `http://localhost:8000` for manual testing. Env var `NEXT_PUBLIC_MEMENTO_API_URL` overrides the default.

---

## File Structure

### New / rewritten files (the entire `ui/` tree)

| Path | Responsibility |
|---|---|
| `ui/package.json` | New deps: `@tanstack/react-query`, `zod`, `react-force-graph-2d`, `lucide-react`, `sonner`, `framer-motion`, `zustand`, `tailwindcss@^4`, `@tailwindcss/postcss`, `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`, `jsdom`. Dev deps for fonts: none (self-hosted via next/font). |
| `ui/next.config.ts` | Keep default plus turbopack disabled for font loading (temporary until next/font + turbo works cleanly). |
| `ui/postcss.config.mjs` | Tailwind v4 via `@tailwindcss/postcss`. |
| `ui/tailwind.config.ts` | Minimal config: `darkMode: 'class'`, content scan paths. Most tokens live in CSS variables so tailwind is thin. |
| `ui/tsconfig.json` | Add path alias `@/*` → `./*`. |
| `ui/vitest.config.ts` | jsdom env, setup file, path alias matching tsconfig. |
| `ui/vitest.setup.ts` | Imports `@testing-library/jest-dom`, mocks `next/font`, polyfills `ResizeObserver`. |
| `ui/app/layout.tsx` | Root layout: fonts, providers, `<Toaster />`, `<CockpitShell>` wrapping `{children}`. |
| `ui/app/page.tsx` | Server component that redirects to `/brain`. |
| `ui/app/globals.css` | All design tokens as CSS variables, reset, font imports, aurora keyframes, reduced-motion media query. |
| `ui/app/brain/page.tsx` | Brain surface client component. |
| `ui/app/brain/loading.tsx` | Skeleton for the Brain route. |
| `ui/app/kb/page.tsx` | KB surface. |
| `ui/app/kb/loading.tsx` | KB skeleton. |
| `ui/app/continuity/page.tsx` | Continuity surface. |
| `ui/app/continuity/loading.tsx` | Continuity skeleton. |
| `ui/app/hygiene/page.tsx` | Hygiene surface (the keystone). |
| `ui/app/hygiene/loading.tsx` | Hygiene skeleton. |
| `ui/components/shell/*` | `cockpit-shell.tsx`, `sidebar-nav.tsx`, `header-bar.tsx`, `project-switcher.tsx`, `health-badge.tsx` |
| `ui/components/ui/*` | Primitives: `button.tsx`, `card.tsx`, `drawer.tsx`, `dialog.tsx`, `badge.tsx`, `empty.tsx`, `skeleton.tsx`, `mono-label.tsx`, `serif-heading.tsx` |
| `ui/components/brain/*` | `brain-scene.tsx`, `brain-canvas.tsx`, `node-drawer.tsx`, `tier-legend.tsx`, `type-legend.tsx`, `graph-stats.tsx` |
| `ui/components/kb/*` | `kb-columns.tsx`, `kb-slice.tsx`, `kb-entry.tsx`, `kb-empty.tsx` |
| `ui/components/continuity/*` | `resume-header.tsx`, `important-section.tsx`, `recent-section.tsx`, `next-steps-list.tsx`, `conflicts-panel.tsx`, `truncated-warning.tsx` |
| `ui/components/hygiene/*` | `pressure-gauges.tsx`, `pressure-explainer.tsx`, `prune-builder.tsx`, `prune-plan-review.tsx`, `prune-apply-gate.tsx`, `prune-apply-dialog.tsx`, `backfill-runner.tsx` |
| `ui/lib/schemas.ts` | All Zod schemas. |
| `ui/lib/types.ts` | `z.infer<>` type exports. |
| `ui/lib/project-store.ts` | Zustand store for current project. |
| `ui/lib/query-client.ts` | Configured `QueryClient`. |
| `ui/lib/theme.ts` | TypeScript references to CSS variables for inline styles. |
| `ui/lib/api/*` | `client.ts`, `health.ts`, `graph.ts`, `detail.ts`, `kb.ts`, `resume.ts`, `pressure.ts`, `prune.ts`, `backfill.ts` |
| `ui/lib/queries/*` | `use-health.ts`, `use-brain-graph.ts`, `use-memory-detail.ts`, `use-kb.ts`, `use-resume.ts`, `use-pressure.ts`, `use-prune.ts`, `use-backfill.ts` |
| `ui/tests/*` | `schemas.test.ts`, `brain-canvas.test.tsx`, `node-drawer.test.tsx`, `kb-columns.test.tsx`, `continuity.test.tsx`, `pressure-gauges.test.tsx`, `prune-flow.test.tsx` |
| `ui/tests/fixtures/*.json` | Captured real responses for contract tests. |
| `ui/public/fonts/*.woff2` | Self-hosted IBM Plex Serif, Inter, JetBrains Mono (subset Latin basic). |

### Files deleted at end of Phase A

All current `ui/app/page.tsx`, `ui/app/layout.tsx`, `ui/app/globals.css`, `ui/components/dashboard.tsx`, `ui/components/brain-canvas.tsx`, `ui/components/kb-panel.tsx`, `ui/components/pressure-panel.tsx`, `ui/components/handoff-panel.tsx`, `ui/lib/api.ts`, `ui/tests/scaffold.test.ts`, `ui/tests/dashboard.test.ts`. All are untracked cosmetic scaffold from before the rebuild.

---

## Phase A — Scaffold & Tokens (Tasks 1-5)

### Task 1: Checkpoint the existing scaffold, then clean slate

**Files:**
- Stage and commit the untracked `ui/` as a checkpoint
- Delete the old scaffold files

- [ ] **Step 1: Commit the untracked scaffold as a checkpoint**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/.gitignore 2>/dev/null || true  # only if present
git add ui/app/ ui/components/ ui/lib/ ui/tests/ ui/package.json ui/package-lock.json ui/next.config.ts ui/tsconfig.json ui/vitest.config.ts ui/next-env.d.ts
git status --short | grep ^A | wc -l
```

Expected: 15-20 files staged.

- [ ] **Step 2: Commit the checkpoint**

```bash
git commit -m "chore(ui): checkpoint scaffold before cockpit rebuild

The current ui/ directory is a cosmetic Next.js scaffold from an earlier
exploration (brain-canvas circle layout, string-dump panels, polled
fetch). This commit preserves it so we have a restore point, then the
cockpit rebuild replaces it entirely.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 3: Delete the old scaffold files**

```bash
cd /Users/demo-user/clawd/memento-mcp
rm ui/app/page.tsx ui/app/layout.tsx ui/app/globals.css
rm ui/components/dashboard.tsx ui/components/brain-canvas.tsx ui/components/kb-panel.tsx ui/components/pressure-panel.tsx ui/components/handoff-panel.tsx
rm ui/lib/api.ts
rm ui/tests/scaffold.test.ts ui/tests/dashboard.test.ts
# Component/lib/tests directories may now be empty — that's fine, we repopulate them.
```

- [ ] **Step 4: Verify the tree is ready for rebuild**

```bash
find ui -type f -not -path '*/node_modules/*' -not -path '*/.next/*'
```

Expected: `package.json`, `package-lock.json`, `tsconfig.json`, `next.config.ts`, `vitest.config.ts`, `next-env.d.ts` remain. The `app/`, `components/`, `lib/`, `tests/` directories exist but are empty.

- [ ] **Step 5: Commit the deletion**

```bash
git add -A ui/
git commit -m "chore(ui): remove old scaffold files in prep for cockpit rebuild

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Rewrite `ui/package.json` and install dependencies

**Files:**
- Modify: `ui/package.json` (full rewrite)
- Modify: `ui/next.config.ts` (add turbopack opt-out for font loader)
- Modify: `ui/tsconfig.json` (add `@/*` path alias)
- Create: `ui/postcss.config.mjs`
- Create: `ui/tailwind.config.ts`

- [ ] **Step 1: Rewrite `ui/package.json`**

```json
{
  "name": "memento-ui",
  "private": true,
  "version": "0.2.0",
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "next lint",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "@tanstack/react-query": "^5.62.0",
    "framer-motion": "^11.11.0",
    "lucide-react": "^0.468.0",
    "next": "^15.5.6",
    "react": "19.1.0",
    "react-dom": "19.1.0",
    "react-force-graph-2d": "^1.27.0",
    "sonner": "^1.7.0",
    "zod": "^3.24.0",
    "zustand": "^5.0.0"
  },
  "devDependencies": {
    "@tailwindcss/postcss": "^4.0.0",
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.1.0",
    "@testing-library/user-event": "^14.5.2",
    "@types/node": "24.6.0",
    "@types/react": "19.1.16",
    "@types/react-dom": "19.1.9",
    "@vitejs/plugin-react": "^4.3.4",
    "jsdom": "^25.0.1",
    "tailwindcss": "^4.0.0",
    "typescript": "5.9.3",
    "vitest": "3.2.4"
  }
}
```

- [ ] **Step 2: Install dependencies**

```bash
cd ui && npm install 2>&1 | tail -10
```

Expected: "added N packages" with no errors. Warnings are acceptable.

If `react-force-graph-2d` has a peer dependency conflict with React 19, retry with `npm install --legacy-peer-deps` and note it in the commit message.

- [ ] **Step 3: Update `ui/next.config.ts`**

Current content is 130 bytes. Replace with:

```typescript
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Proxy to the backend for API calls so we don't need CORS
  async rewrites() {
    const apiUrl = process.env.NEXT_PUBLIC_MEMENTO_API_URL || "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
      {
        source: "/health",
        destination: `${apiUrl}/health`,
      },
    ];
  },
};

export default nextConfig;
```

- [ ] **Step 4: Update `ui/tsconfig.json`**

Find `"paths"` (may be absent). Add/update:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": {
      "@/*": ["./*"]
    }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 5: Create `ui/postcss.config.mjs`**

```javascript
const config = {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};

export default config;
```

- [ ] **Step 6: Create `ui/tailwind.config.ts`**

```typescript
import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        serif: ["var(--font-serif)", "Georgia", "serif"],
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
```

- [ ] **Step 7: Run the dev build to confirm config works**

```bash
cd ui && npm run build 2>&1 | tail -15
```

Expected: the build MAY fail on missing `globals.css` content or `layout.tsx` — that's fine for this task. What matters is that tailwind, postcss, and tsconfig do not throw. If there's an error about paths, fix it now.

- [ ] **Step 8: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/package.json ui/package-lock.json ui/next.config.ts ui/tsconfig.json ui/postcss.config.mjs ui/tailwind.config.ts
git commit -m "chore(ui): rewrite package.json with cockpit deps; add tailwind v4 + postcss

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Design tokens, fonts, globals.css, vitest setup

**Files:**
- Create: `ui/app/globals.css`
- Create: `ui/app/layout.tsx` (minimal; Task 8 fills in providers)
- Create: `ui/app/page.tsx` (redirect to `/brain`)
- Create: `ui/vitest.config.ts` (replace existing)
- Create: `ui/vitest.setup.ts`
- Create: `ui/public/fonts/.gitkeep`
- Create: `ui/lib/theme.ts`

- [ ] **Step 1: Create `ui/app/globals.css`**

```css
/* Tailwind v4 import */
@import "tailwindcss";

/* ---------------------------------------------------------------------- */
/* Design tokens — Brain Observatory                                       */
/* ---------------------------------------------------------------------- */

:root {
  /* Fonts (wired up by next/font in layout.tsx) */
  --font-serif: "IBM Plex Serif", Georgia, serif;
  --font-sans: "Inter", system-ui, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, monospace;

  /* Backgrounds — cinematic dark, no pure #000 */
  --bg-deep: #020617;
  --bg-base: #0a0f1f;
  --bg-elevated: #0f172a;
  --bg-frost: rgba(15, 23, 42, 0.72);

  /* Surfaces */
  --surface-0: rgba(148, 163, 184, 0.03);
  --surface-1: rgba(148, 163, 184, 0.06);
  --surface-2: rgba(148, 163, 184, 0.09);
  --border: rgba(148, 163, 184, 0.12);
  --border-strong: rgba(148, 163, 184, 0.24);

  /* Foreground */
  --fg: #f1f5f9;
  --fg-muted: #94a3b8;
  --fg-dim: #64748b;
  --fg-serif: #f8fafc;

  /* Accents */
  --accent-primary: #60a5fa;
  --accent-secondary: #a78bfa;
  --accent-danger: #f87171;
  --accent-warning: #f59e0b;
  --accent-success: #34d399;

  /* Tier colors */
  --tier-identity: #fbbf24;
  --tier-semantic: #a78bfa;
  --tier-episodic: #60a5fa;
  --tier-working: #94a3b8;

  /* Memory type colors */
  --type-fact: #60a5fa;
  --type-decision: #f59e0b;
  --type-preference: #c084fc;
  --type-learning: #34d399;
  --type-requirement: #f87171;
  --type-note: #94a3b8;
  --type-session: #cbd5e1;

  /* Aurora mesh stops */
  --aurora-1: rgba(96, 165, 250, 0.18);
  --aurora-2: rgba(167, 139, 250, 0.14);
  --aurora-3: rgba(34, 211, 238, 0.10);

  /* Motion */
  --ease-out-quint: cubic-bezier(0.22, 1, 0.36, 1);
  --ease-expo-out: cubic-bezier(0.16, 1, 0.3, 1);
  --dur-fast: 150ms;
  --dur-med: 280ms;
  --dur-slow: 420ms;
  --dur-breath: 4s;

  /* Radii */
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 18px;
  --radius-xl: 24px;

  /* Z-index scale */
  --z-shell: 10;
  --z-drawer: 40;
  --z-modal: 60;
  --z-toast: 80;
}

/* ---------------------------------------------------------------------- */
/* Reset                                                                    */
/* ---------------------------------------------------------------------- */

*,
*::before,
*::after {
  box-sizing: border-box;
}

html,
body {
  margin: 0;
  padding: 0;
  background: var(--bg-deep);
  color: var(--fg);
  font-family: var(--font-sans);
  font-size: 15px;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  min-height: 100vh;
}

h1,
h2,
h3,
h4 {
  font-family: var(--font-serif);
  color: var(--fg-serif);
  line-height: 1.2;
  font-weight: 500;
}

code,
kbd,
samp,
.mono {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}

::selection {
  background: var(--accent-primary);
  color: var(--bg-deep);
}

/* ---------------------------------------------------------------------- */
/* Aurora background (used only on /brain)                                  */
/* ---------------------------------------------------------------------- */

.aurora-bg {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(ellipse at 20% 30%, var(--aurora-1) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 70%, var(--aurora-2) 0%, transparent 55%),
    radial-gradient(ellipse at 50% 90%, var(--aurora-3) 0%, transparent 60%),
    var(--bg-deep);
  animation: aurora-breathe var(--dur-breath) ease-in-out infinite;
  pointer-events: none;
}

@keyframes aurora-breathe {
  0%, 100% {
    filter: hue-rotate(0deg) brightness(1);
    transform: scale(1);
  }
  50% {
    filter: hue-rotate(8deg) brightness(1.05);
    transform: scale(1.015);
  }
}

/* Starfield — 800 bytes of pure decoration */
.starfield::before {
  content: "";
  position: absolute;
  inset: 0;
  background-image:
    radial-gradient(1px 1px at 20% 30%, rgba(255,255,255,0.6) 50%, transparent 100%),
    radial-gradient(1px 1px at 60% 70%, rgba(255,255,255,0.4) 50%, transparent 100%),
    radial-gradient(1px 1px at 85% 15%, rgba(255,255,255,0.5) 50%, transparent 100%),
    radial-gradient(1px 1px at 35% 85%, rgba(255,255,255,0.3) 50%, transparent 100%),
    radial-gradient(1px 1px at 75% 40%, rgba(255,255,255,0.5) 50%, transparent 100%),
    radial-gradient(1px 1px at 10% 60%, rgba(255,255,255,0.4) 50%, transparent 100%),
    radial-gradient(1px 1px at 50% 10%, rgba(255,255,255,0.4) 50%, transparent 100%);
  background-size: 400px 400px;
  opacity: 0.7;
  pointer-events: none;
}

/* ---------------------------------------------------------------------- */
/* Reduced motion                                                           */
/* ---------------------------------------------------------------------- */

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }

  .aurora-bg {
    animation: none;
  }
}

/* ---------------------------------------------------------------------- */
/* Scrollbar (subtle)                                                       */
/* ---------------------------------------------------------------------- */

::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: var(--surface-2);
  border-radius: 5px;
}

::-webkit-scrollbar-thumb:hover {
  background: var(--border-strong);
}
```

- [ ] **Step 2: Create `ui/app/layout.tsx` (minimal version — Task 8 adds providers)**

```typescript
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Memento — Memory Cockpit",
  description: "Brain Observatory for the Memento MCP memory system",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body>{children}</body>
    </html>
  );
}
```

- [ ] **Step 3: Create `ui/app/page.tsx`**

```typescript
import { redirect } from "next/navigation";

export default function RootPage() {
  redirect("/brain");
}
```

- [ ] **Step 4: Create `ui/lib/theme.ts`**

```typescript
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
```

- [ ] **Step 5: Rewrite `ui/vitest.config.ts`**

```typescript
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    globals: true,
    css: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});
```

- [ ] **Step 6: Create `ui/vitest.setup.ts`**

```typescript
import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// Polyfill ResizeObserver used by react-force-graph-2d
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(globalThis as any).ResizeObserver = ResizeObserverStub;

// Mock next/font — real loader requires a real Next.js build context
vi.mock("next/font/local", () => ({
  default: () => ({
    variable: "--font-mocked",
    className: "font-mocked",
    style: { fontFamily: "mock" },
  }),
}));

// Mock framer-motion's useReducedMotion (not present without a window)
vi.mock("framer-motion", async (orig) => {
  const real = await orig<typeof import("framer-motion")>();
  return { ...real };
});
```

- [ ] **Step 7: Create `ui/public/fonts/.gitkeep`**

```bash
mkdir -p ui/public/fonts
touch ui/public/fonts/.gitkeep
```

(Actual font files will be added in Task 8 when the layout wires them up with `next/font/local`. For now we just reserve the directory.)

- [ ] **Step 8: Verify the dev server starts**

```bash
cd ui && timeout 15 npm run dev 2>&1 | head -20
```

Expected: `Ready in Nms`, no errors. A 404 on `/` → `/brain` is fine (the /brain route doesn't exist yet). Kill the server with Ctrl-C if needed.

- [ ] **Step 9: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/app/globals.css ui/app/layout.tsx ui/app/page.tsx ui/lib/theme.ts ui/vitest.config.ts ui/vitest.setup.ts ui/public/fonts/.gitkeep
git commit -m "feat(ui): design tokens, globals.css, vitest setup, theme references

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: QueryClient provider, project store, Sonner toaster

**Files:**
- Create: `ui/lib/query-client.ts`
- Create: `ui/lib/project-store.ts`
- Create: `ui/components/providers.tsx`
- Modify: `ui/app/layout.tsx` (wrap with providers)

- [ ] **Step 1: Create `ui/lib/query-client.ts`**

```typescript
import { QueryClient } from "@tanstack/react-query";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 10_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: true,
        retry: 2,
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
      },
      mutations: {
        retry: 0,
      },
    },
  });
}
```

- [ ] **Step 2: Create `ui/lib/project-store.ts`**

```typescript
import { create } from "zustand";

type ProjectStore = {
  project: string;
  setProject: (project: string) => void;
};

export const useProjectStore = create<ProjectStore>((set) => ({
  project: "general",
  setProject: (project) => set({ project }),
}));
```

- [ ] **Step 3: Create `ui/components/providers.tsx`**

```typescript
"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { Toaster } from "sonner";

import { createQueryClient } from "@/lib/query-client";

export function Providers({ children }: { children: React.ReactNode }) {
  // Keep the client stable across re-renders within a single session.
  const [client] = useState(() => createQueryClient());

  return (
    <QueryClientProvider client={client}>
      {children}
      <Toaster
        position="bottom-right"
        theme="dark"
        toastOptions={{
          style: {
            background: "var(--bg-frost)",
            border: "1px solid var(--border)",
            color: "var(--fg)",
            backdropFilter: "blur(18px) saturate(1.2)",
          },
        }}
      />
    </QueryClientProvider>
  );
}
```

- [ ] **Step 4: Update `ui/app/layout.tsx` to wrap in Providers**

Replace the file:

```typescript
import type { Metadata } from "next";
import { Providers } from "@/components/providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "Memento — Memory Cockpit",
  description: "Brain Observatory for the Memento MCP memory system",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
```

- [ ] **Step 5: Confirm the app still compiles**

```bash
cd ui && timeout 15 npm run dev 2>&1 | head -20
```

Expected: `Ready in Nms`, no compile errors.

- [ ] **Step 6: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/lib/query-client.ts ui/lib/project-store.ts ui/components/providers.tsx ui/app/layout.tsx
git commit -m "feat(ui): QueryClient + project store + Sonner toaster wiring

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: UI primitives (button, card, badge, drawer, dialog, empty, skeleton, mono-label, serif-heading)

**Files:**
- Create: `ui/components/ui/button.tsx`
- Create: `ui/components/ui/card.tsx`
- Create: `ui/components/ui/badge.tsx`
- Create: `ui/components/ui/drawer.tsx`
- Create: `ui/components/ui/dialog.tsx`
- Create: `ui/components/ui/empty.tsx`
- Create: `ui/components/ui/skeleton.tsx`
- Create: `ui/components/ui/mono-label.tsx`
- Create: `ui/components/ui/serif-heading.tsx`

These are small, composable primitives used across all four surfaces. All are client components where needed.

- [ ] **Step 1: `ui/components/ui/button.tsx`**

```typescript
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
```

- [ ] **Step 2: `ui/components/ui/card.tsx`**

```typescript
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
```

- [ ] **Step 3: `ui/components/ui/badge.tsx`**

```typescript
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
```

- [ ] **Step 4: `ui/components/ui/drawer.tsx`**

```typescript
"use client";

import { useEffect, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";

type Props = {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
};

export function Drawer({ open, onClose, title, children }: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            role="presentation"
            onClick={onClose}
            className="fixed inset-0 bg-black/60"
            style={{ zIndex: "var(--z-drawer)" }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
          />
          <motion.aside
            role="dialog"
            aria-modal="true"
            className="fixed right-0 top-0 h-full w-full max-w-[480px] overflow-y-auto border-l border-[var(--border)] bg-[var(--bg-frost)] p-6 backdrop-blur-[18px] backdrop-saturate-150"
            style={{ zIndex: "var(--z-drawer)" }}
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
          >
            <div className="mb-4 flex items-start justify-between gap-4">
              <div className="min-w-0 flex-1">{title}</div>
              <button
                onClick={onClose}
                aria-label="Close drawer"
                className="rounded-md p-1 text-[var(--fg-muted)] hover:bg-[var(--surface-1)] hover:text-[var(--fg)]"
              >
                <X size={18} />
              </button>
            </div>
            {children}
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
```

- [ ] **Step 5: `ui/components/ui/dialog.tsx`**

```typescript
"use client";

import { useEffect, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";

type Props = {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
};

export function Dialog({ open, onClose, title, children }: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 flex items-center justify-center p-4"
          style={{ zIndex: "var(--z-modal)" }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
        >
          <div className="absolute inset-0 bg-black/70" onClick={onClose} />
          <motion.div
            className="relative w-full max-w-md rounded-[var(--radius-lg)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] p-6 shadow-[0_20px_60px_rgba(0,0,0,0.6)]"
            initial={{ scale: 0.96, y: 8 }}
            animate={{ scale: 1, y: 0 }}
            exit={{ scale: 0.96, y: 8 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
          >
            <h2 className="mb-4 font-serif text-2xl">{title}</h2>
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
```

- [ ] **Step 6: `ui/components/ui/empty.tsx`**

```typescript
import type { ReactNode } from "react";

type Props = {
  title: string;
  hint?: ReactNode;
};

export function Empty({ title, hint }: Props) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
      <p className="font-serif text-lg text-[var(--fg-muted)]">{title}</p>
      {hint ? <p className="text-sm text-[var(--fg-dim)]">{hint}</p> : null}
    </div>
  );
}
```

- [ ] **Step 7: `ui/components/ui/skeleton.tsx`**

```typescript
import type { HTMLAttributes } from "react";

export function Skeleton({ className = "", ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`animate-pulse rounded-md bg-[var(--surface-1)] ${className}`}
      {...rest}
    />
  );
}
```

- [ ] **Step 8: `ui/components/ui/mono-label.tsx`**

```typescript
import type { HTMLAttributes } from "react";

export function MonoLabel({ className = "", ...rest }: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={`font-mono text-[11px] uppercase tracking-[0.08em] text-[var(--fg-muted)] ${className}`}
      {...rest}
    />
  );
}
```

- [ ] **Step 9: `ui/components/ui/serif-heading.tsx`**

```typescript
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
```

- [ ] **Step 10: Typecheck**

```bash
cd ui && npx tsc --noEmit 2>&1 | tail -10
```

Expected: no errors from the new files. If `@/lib/theme` can't be resolved, check the tsconfig path alias from Task 2.

- [ ] **Step 11: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/components/ui/
git commit -m "feat(ui): primitives — button, card, badge, drawer, dialog, empty, skeleton, labels

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Phase B — Shell (Tasks 6-8)

### Task 6: CockpitShell + SidebarNav

**Files:**
- Create: `ui/components/shell/cockpit-shell.tsx`
- Create: `ui/components/shell/sidebar-nav.tsx`

- [ ] **Step 1: `ui/components/shell/sidebar-nav.tsx`**

```typescript
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Brain, BookOpen, Clock, Sparkles } from "lucide-react";

const navItems = [
  { href: "/brain", label: "Brain", icon: Brain },
  { href: "/kb", label: "Knowledge", icon: BookOpen },
  { href: "/continuity", label: "Continuity", icon: Clock },
  { href: "/hygiene", label: "Hygiene", icon: Sparkles },
] as const;

export function SidebarNav() {
  const pathname = usePathname();

  return (
    <nav aria-label="Primary" className="flex flex-col gap-1">
      {navItems.map((item) => {
        const active = pathname?.startsWith(item.href);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors duration-[150ms] ${
              active
                ? "bg-[var(--surface-1)] text-[var(--fg)] shadow-[inset_2px_0_0_var(--accent-primary)]"
                : "text-[var(--fg-muted)] hover:bg-[var(--surface-0)] hover:text-[var(--fg)]"
            }`}
          >
            <Icon size={16} />
            <span>{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
```

- [ ] **Step 2: `ui/components/shell/cockpit-shell.tsx`**

```typescript
"use client";

import type { ReactNode } from "react";
import { SerifHeading } from "@/components/ui/serif-heading";
import { SidebarNav } from "./sidebar-nav";
import { ProjectSwitcher } from "./project-switcher";
import { HealthBadge } from "./health-badge";
import { HeaderBar } from "./header-bar";

export function CockpitShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen bg-[var(--bg-deep)]">
      <aside
        className="flex w-60 flex-col gap-6 border-r border-[var(--border)] bg-[var(--bg-base)] px-4 py-6"
        style={{ zIndex: "var(--z-shell)" }}
      >
        <SerifHeading eyebrow="MEMENTO" title="Cockpit" size="section" />
        <SidebarNav />
        <div className="mt-auto flex flex-col gap-3">
          <ProjectSwitcher />
          <HealthBadge />
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <HeaderBar />
        <main className="flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Typecheck — expected to fail on missing ProjectSwitcher/HealthBadge/HeaderBar**

```bash
cd ui && npx tsc --noEmit 2>&1 | tail -10
```

Expected: errors on `./project-switcher`, `./health-badge`, `./header-bar`. Task 7 creates them. Do not commit yet — commit after Task 7.

---

### Task 7: HeaderBar, ProjectSwitcher, HealthBadge

**Files:**
- Create: `ui/components/shell/header-bar.tsx`
- Create: `ui/components/shell/project-switcher.tsx`
- Create: `ui/components/shell/health-badge.tsx`
- Create: `ui/lib/api/client.ts` (minimal fetch wrapper — will be extended in Phase C)
- Create: `ui/lib/api/health.ts`
- Create: `ui/lib/queries/use-health.ts`
- Create: `ui/lib/schemas.ts` (HealthSchema only — extended in Phase C)

- [ ] **Step 1: `ui/lib/schemas.ts` (stub)**

```typescript
import { z } from "zod";

// Extended in Phase C — Task 9
export const HealthSchema = z.object({
  status: z.string(),
  transport: z.string().optional(),
  tools_enabled: z.array(z.string()).optional(),
});

export type Health = z.infer<typeof HealthSchema>;
```

- [ ] **Step 2: `ui/lib/api/client.ts`**

```typescript
export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

export async function fetchJson<T>(
  path: string,
  init?: RequestInit,
  parse?: (data: unknown) => T
): Promise<T> {
  const url = path.startsWith("http") ? path : path; // Proxied via next.config rewrites
  const res = await fetch(url, {
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = await res.text();
    }
    throw new ApiError(res.status, `Request failed: ${res.status}`, body);
  }
  const data = await res.json();
  return parse ? parse(data) : (data as T);
}
```

- [ ] **Step 3: `ui/lib/api/health.ts`**

```typescript
import { fetchJson } from "./client";
import { HealthSchema, type Health } from "@/lib/schemas";

export function getHealth(): Promise<Health> {
  return fetchJson("/health", undefined, (data) => HealthSchema.parse(data));
}
```

- [ ] **Step 4: `ui/lib/queries/use-health.ts`**

```typescript
import { useQuery } from "@tanstack/react-query";
import { getHealth } from "@/lib/api/health";

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
}
```

- [ ] **Step 5: `ui/components/shell/health-badge.tsx`**

```typescript
"use client";

import { useHealth } from "@/lib/queries/use-health";

export function HealthBadge() {
  const { data, isError, isLoading } = useHealth();
  const status = isError ? "offline" : isLoading ? "…" : data?.status ?? "unknown";
  const color =
    status === "healthy" ? "var(--accent-success)" : isError ? "var(--accent-danger)" : "var(--fg-dim)";

  return (
    <div className="flex items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface-0)] px-3 py-2">
      <span
        className="h-2 w-2 rounded-full"
        style={{ background: color, boxShadow: `0 0 8px ${color}` }}
      />
      <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-[var(--fg-muted)]">
        {status}
      </span>
    </div>
  );
}
```

- [ ] **Step 6: `ui/components/shell/project-switcher.tsx`**

```typescript
"use client";

import { FolderGit2 } from "lucide-react";
import { useProjectStore } from "@/lib/project-store";

export function ProjectSwitcher() {
  const project = useProjectStore((s) => s.project);
  const setProject = useProjectStore((s) => s.setProject);

  return (
    <label className="flex flex-col gap-1.5 rounded-md border border-[var(--border)] bg-[var(--surface-0)] px-3 py-2">
      <span className="flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.08em] text-[var(--fg-muted)]">
        <FolderGit2 size={12} />
        project
      </span>
      <input
        value={project}
        onChange={(e) => setProject(e.target.value)}
        aria-label="Project name"
        className="bg-transparent text-sm text-[var(--fg)] placeholder:text-[var(--fg-dim)] focus:outline-none"
        placeholder="general"
      />
    </label>
  );
}
```

- [ ] **Step 7: `ui/components/shell/header-bar.tsx`**

```typescript
"use client";

import { usePathname } from "next/navigation";
import { useState, useEffect } from "react";
import { RefreshCw } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { MonoLabel } from "@/components/ui/mono-label";

const titles: Record<string, string> = {
  "/brain": "Neural Graph",
  "/kb": "Knowledge Base",
  "/continuity": "Continuity Console",
  "/hygiene": "Memory Hygiene",
};

export function HeaderBar() {
  const pathname = usePathname() ?? "";
  const title = Object.entries(titles).find(([k]) => pathname.startsWith(k))?.[1] ?? "Cockpit";
  const [now, setNow] = useState<string>("");
  const qc = useQueryClient();

  useEffect(() => {
    const tick = () => setNow(new Date().toLocaleTimeString());
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <header className="sticky top-0 flex h-14 items-center justify-between border-b border-[var(--border)] bg-[var(--bg-base)]/80 px-6 backdrop-blur-[12px]">
      <h1 className="font-serif text-xl">{title}</h1>
      <div className="flex items-center gap-3">
        <MonoLabel>now {now}</MonoLabel>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => qc.invalidateQueries()}
          aria-label="Refresh all data"
        >
          <RefreshCw size={14} />
          Refresh
        </Button>
      </div>
    </header>
  );
}
```

- [ ] **Step 8: Typecheck**

```bash
cd ui && npx tsc --noEmit 2>&1 | tail -10
```

Expected: no errors.

- [ ] **Step 9: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/components/shell/ ui/lib/api/ ui/lib/queries/use-health.ts ui/lib/schemas.ts
git commit -m "feat(ui): shell — CockpitShell, SidebarNav, HeaderBar, ProjectSwitcher, HealthBadge

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Wire shell into root layout, create 4 route stubs + loading.tsx

**Files:**
- Modify: `ui/app/layout.tsx` (add CockpitShell wrap)
- Create: `ui/app/brain/page.tsx`, `ui/app/brain/loading.tsx`
- Create: `ui/app/kb/page.tsx`, `ui/app/kb/loading.tsx`
- Create: `ui/app/continuity/page.tsx`, `ui/app/continuity/loading.tsx`
- Create: `ui/app/hygiene/page.tsx`, `ui/app/hygiene/loading.tsx`

These route pages are stubs for now. Phases D-F replace them with real implementations.

- [ ] **Step 1: Update `ui/app/layout.tsx`**

```typescript
import type { Metadata } from "next";
import { Providers } from "@/components/providers";
import { CockpitShell } from "@/components/shell/cockpit-shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "Memento — Memory Cockpit",
  description: "Brain Observatory for the Memento MCP memory system",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body>
        <Providers>
          <CockpitShell>{children}</CockpitShell>
        </Providers>
      </body>
    </html>
  );
}
```

- [ ] **Step 2: Create the 4 page stubs**

`ui/app/brain/page.tsx`:
```typescript
"use client";
export default function BrainPage() {
  return <div className="p-6 font-serif text-xl text-[var(--fg-muted)]">Brain — coming soon</div>;
}
```

`ui/app/kb/page.tsx`:
```typescript
"use client";
export default function KbPage() {
  return <div className="p-6 font-serif text-xl text-[var(--fg-muted)]">KB — coming soon</div>;
}
```

`ui/app/continuity/page.tsx`:
```typescript
"use client";
export default function ContinuityPage() {
  return <div className="p-6 font-serif text-xl text-[var(--fg-muted)]">Continuity — coming soon</div>;
}
```

`ui/app/hygiene/page.tsx`:
```typescript
"use client";
export default function HygienePage() {
  return <div className="p-6 font-serif text-xl text-[var(--fg-muted)]">Hygiene — coming soon</div>;
}
```

- [ ] **Step 3: Create the 4 loading.tsx stubs**

Each file has the same content, differing only by label:

`ui/app/brain/loading.tsx`:
```typescript
import { Skeleton } from "@/components/ui/skeleton";
export default function Loading() {
  return (
    <div className="space-y-4 p-6">
      <Skeleton className="h-10 w-64" />
      <Skeleton className="h-[480px] w-full" />
    </div>
  );
}
```

Duplicate for `kb/loading.tsx`, `continuity/loading.tsx`, `hygiene/loading.tsx` (same content — each surface has its own skeleton identity later, but a uniform stub is fine for now).

- [ ] **Step 4: Start the dev server and verify all four routes render**

Start the backend first:
```bash
cd /Users/demo-user/clawd/memento-mcp
docker compose up -d qdrant  # or verify it's already running
MCP_TRANSPORT=streamable-http HOST=0.0.0.0 PORT=8000 QDRANT_URL=http://localhost:6333 uv run python -m server &
```

Then:
```bash
cd ui && npm run dev &
```

Wait ~3s, then:
```bash
curl -sf http://localhost:3000/brain | grep -o "Brain — coming soon" | head -1
curl -sf http://localhost:3000/kb | grep -o "KB — coming soon" | head -1
curl -sf http://localhost:3000/continuity | grep -o "Continuity — coming soon" | head -1
curl -sf http://localhost:3000/hygiene | grep -o "Hygiene — coming soon" | head -1
```

Expected: all four lines match. Kill the dev server and the backend when done.

- [ ] **Step 5: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/app/
git commit -m "feat(ui): wire CockpitShell into root layout and add 4 route stubs

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Phase C — Data layer (Tasks 9-12)

### Task 9: Full Zod schemas and types

**Files:**
- Modify: `ui/lib/schemas.ts` (extend — this is the full schema file)
- Create: `ui/lib/types.ts`

- [ ] **Step 1: Rewrite `ui/lib/schemas.ts`**

```typescript
import { z } from "zod";

// ----- Health --------------------------------------------------------------

export const HealthSchema = z.object({
  status: z.string(),
  transport: z.string().optional(),
  tools_enabled: z.array(z.string()).optional(),
});

// ----- Memory core ---------------------------------------------------------

export const MemorySchema = z.object({
  memory_id: z.string(),
  content: z.string().optional(),
  type: z.string().optional(),
  tier: z.enum(["working", "episodic", "semantic", "identity"]).optional(),
  durability: z.number().optional(),
  reinforcement_count: z.number().optional(),
  lifecycle_reason: z.string().optional(),
  date: z.string().optional(),
  project: z.string().optional(),
  salience: z.number().optional(),
}).passthrough(); // allow unknown fields from older payloads

// ----- Graph ---------------------------------------------------------------

export const GraphNodeSchema = z.object({
  id: z.string(),
  type: z.string().optional(),
  content: z.string().optional(),
  tier: z.string().optional(),
  durability: z.number().optional(),
  degree: z.number().optional(),
}).passthrough();

export const GraphLinkSchema = z.object({
  source: z.union([z.string(), z.any()]),
  target: z.union([z.string(), z.any()]),
  weight: z.number().optional(),
  relation: z.string().optional(),
}).passthrough();

export const GraphResponseSchema = z.object({
  graph: z
    .object({
      nodes: z.array(GraphNodeSchema),
      links: z.array(GraphLinkSchema),
    })
    .optional(),
}).passthrough();

// ----- Detail --------------------------------------------------------------

export const MemoryNeighborSchema = z.object({
  relation: z.string(),
  memory: MemorySchema,
});

export const DetailResponseSchema = z.object({
  memory: MemorySchema.nullable(),
  neighbors: z.array(MemoryNeighborSchema),
  scope: z
    .object({
      project: z.string().nullable().optional(),
      agent: z.string().nullable().optional(),
      repo_name: z.string().nullable().optional(),
    })
    .nullable(),
});

// ----- KB ------------------------------------------------------------------

export const KbEntrySchema = z.object({
  memory_id: z.string().nullable(),
  type: z.string().nullable(),
  tier: z.string().nullable(),
  date: z.string().nullable(),
  summary: z.string(),
  content: z.string().optional(),
});

export const KbResponseSchema = z.object({
  project: z.string(),
  decisions: z.array(KbEntrySchema),
  requirements: z.array(KbEntrySchema),
  preferences: z.array(KbEntrySchema),
  learnings: z.array(KbEntrySchema),
});

// ----- Pressure ------------------------------------------------------------

export const PressureResponseSchema = z.object({
  project: z.string(),
  load_score: z.number(),
  capacity: z.number(),
  flagged: z.object({
    stale_working_count: z.number(),
    low_value_count: z.number(),
    contradiction_count: z.number(),
  }),
  candidates: z.array(z.record(z.string(), z.any())),
});

// ----- Prune ---------------------------------------------------------------

export const PruneCandidateSchema = z.object({
  memory_id: z.string(),
  tier: z.string(),
  reason: z.string(),
  age_days: z.number(),
  salience: z.number(),
});

export const PrunePlanSchema = z.object({
  plan_id: z.string(),
  project: z.string(),
  generated_at: z.string(),
  expires_at: z.string(),
  summary: z.string(),
  candidates: z.array(PruneCandidateSchema),
});

export const PruneApplyResponseSchema = z.object({
  plan_id: z.string(),
  deleted: z.array(z.string()),
  skipped: z.array(z.string()),
});

// ----- Backfill ------------------------------------------------------------

export const BackfillReportSchema = z.object({
  dry_run: z.boolean(),
  project: z.string().nullable(),
  updated_by_tier: z.record(z.string(), z.number()),
  skipped: z.array(z.string()),
  errors: z.array(z.object({ memory_id: z.string(), error: z.string() })),
  total: z.number(),
});

// ----- Resume --------------------------------------------------------------

export const ResumeResponseSchema = z.object({
  scope: z.record(z.string(), z.any()),
  recent: z.array(z.any()),
  important: z.array(z.any()),
  unresolved: z.array(z.any()),
  next_steps: z.array(z.any()),
  handoff: z.string().nullable(),
  pressure: z.any(),
  pressure_report: z.string().optional(),
  truncated: z.boolean(),
  summary: z.string().optional(),
}).passthrough();

// Re-exports for convenience
export type Health = z.infer<typeof HealthSchema>;
export type Memory = z.infer<typeof MemorySchema>;
export type GraphNode = z.infer<typeof GraphNodeSchema>;
export type GraphLink = z.infer<typeof GraphLinkSchema>;
export type GraphResponse = z.infer<typeof GraphResponseSchema>;
export type DetailResponse = z.infer<typeof DetailResponseSchema>;
export type KbEntry = z.infer<typeof KbEntrySchema>;
export type KbResponse = z.infer<typeof KbResponseSchema>;
export type PressureResponse = z.infer<typeof PressureResponseSchema>;
export type PruneCandidate = z.infer<typeof PruneCandidateSchema>;
export type PrunePlan = z.infer<typeof PrunePlanSchema>;
export type PruneApplyResponse = z.infer<typeof PruneApplyResponseSchema>;
export type BackfillReport = z.infer<typeof BackfillReportSchema>;
export type ResumeResponse = z.infer<typeof ResumeResponseSchema>;
```

- [ ] **Step 2: Create `ui/lib/types.ts` as a barrel**

```typescript
export type {
  Health,
  Memory,
  GraphNode,
  GraphLink,
  GraphResponse,
  DetailResponse,
  KbEntry,
  KbResponse,
  PressureResponse,
  PruneCandidate,
  PrunePlan,
  PruneApplyResponse,
  BackfillReport,
  ResumeResponse,
} from "./schemas";
```

- [ ] **Step 3: Typecheck**

```bash
cd ui && npx tsc --noEmit 2>&1 | tail -5
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/lib/schemas.ts ui/lib/types.ts
git commit -m "feat(ui): full Zod schemas for all 9 backend endpoints

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: All typed API clients

**Files:**
- Create: `ui/lib/api/graph.ts`
- Create: `ui/lib/api/detail.ts`
- Create: `ui/lib/api/kb.ts`
- Create: `ui/lib/api/resume.ts`
- Create: `ui/lib/api/pressure.ts`
- Create: `ui/lib/api/prune.ts`
- Create: `ui/lib/api/backfill.ts`

- [ ] **Step 1: `ui/lib/api/graph.ts`**

```typescript
import { fetchJson } from "./client";
import { GraphResponseSchema, type GraphResponse } from "@/lib/schemas";

export function getGraph(project: string, limit = 400): Promise<GraphResponse> {
  const qs = new URLSearchParams({ project, limit: String(limit) });
  return fetchJson(`/api/memory/graph?${qs}`, undefined, (d) => GraphResponseSchema.parse(d));
}
```

- [ ] **Step 2: `ui/lib/api/detail.ts`**

```typescript
import { fetchJson } from "./client";
import { DetailResponseSchema, type DetailResponse } from "@/lib/schemas";

export function getMemoryDetail(memoryId: string): Promise<DetailResponse> {
  return fetchJson(`/api/memory/detail/${encodeURIComponent(memoryId)}`, undefined, (d) =>
    DetailResponseSchema.parse(d)
  );
}
```

- [ ] **Step 3: `ui/lib/api/kb.ts`**

```typescript
import { fetchJson } from "./client";
import { KbResponseSchema, type KbResponse } from "@/lib/schemas";

export function getKb(project: string): Promise<KbResponse> {
  const qs = new URLSearchParams({ project });
  return fetchJson(`/api/memory/kb?${qs}`, undefined, (d) => KbResponseSchema.parse(d));
}
```

- [ ] **Step 4: `ui/lib/api/resume.ts`**

```typescript
import { fetchJson } from "./client";
import { ResumeResponseSchema, type ResumeResponse } from "@/lib/schemas";

export function getResume(project: string): Promise<ResumeResponse> {
  const qs = new URLSearchParams({ project });
  return fetchJson(`/api/memory/resume?${qs}`, undefined, (d) => ResumeResponseSchema.parse(d));
}
```

- [ ] **Step 5: `ui/lib/api/pressure.ts`**

```typescript
import { fetchJson } from "./client";
import { PressureResponseSchema, type PressureResponse } from "@/lib/schemas";

export function getPressure(project: string): Promise<PressureResponse> {
  const qs = new URLSearchParams({ project });
  return fetchJson(`/api/memory/pressure?${qs}`, undefined, (d) => PressureResponseSchema.parse(d));
}
```

- [ ] **Step 6: `ui/lib/api/prune.ts`**

```typescript
import { fetchJson } from "./client";
import {
  PrunePlanSchema,
  PruneApplyResponseSchema,
  type PrunePlan,
  type PruneApplyResponse,
} from "@/lib/schemas";

export function postPrunePlan(project: string, limit = 200): Promise<PrunePlan> {
  return fetchJson(
    "/api/memory/prune/plan",
    {
      method: "POST",
      body: JSON.stringify({ project, limit }),
    },
    (d) => PrunePlanSchema.parse(d)
  );
}

export function postPruneApply(planId: string, confirm: string): Promise<PruneApplyResponse> {
  return fetchJson(
    "/api/memory/prune/apply",
    {
      method: "POST",
      body: JSON.stringify({ plan_id: planId, confirm }),
    },
    (d) => PruneApplyResponseSchema.parse(d)
  );
}
```

- [ ] **Step 7: `ui/lib/api/backfill.ts`**

```typescript
import { fetchJson } from "./client";
import { BackfillReportSchema, type BackfillReport } from "@/lib/schemas";

export function postBackfill(opts: { dry_run: boolean; project?: string }): Promise<BackfillReport> {
  return fetchJson(
    "/api/memory/lifecycle/backfill",
    {
      method: "POST",
      body: JSON.stringify(opts),
    },
    (d) => BackfillReportSchema.parse(d)
  );
}
```

- [ ] **Step 8: Typecheck**

```bash
cd ui && npx tsc --noEmit 2>&1 | tail -5
```

Expected: no errors.

- [ ] **Step 9: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/lib/api/
git commit -m "feat(ui): typed API clients for all 9 backend endpoints

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: TanStack Query hooks

**Files:**
- Create: `ui/lib/queries/use-brain-graph.ts`
- Create: `ui/lib/queries/use-memory-detail.ts`
- Create: `ui/lib/queries/use-kb.ts`
- Create: `ui/lib/queries/use-resume.ts`
- Create: `ui/lib/queries/use-pressure.ts`
- Create: `ui/lib/queries/use-prune.ts`
- Create: `ui/lib/queries/use-backfill.ts`

- [ ] **Step 1: `ui/lib/queries/use-brain-graph.ts`**

```typescript
import { useQuery } from "@tanstack/react-query";
import { getGraph } from "@/lib/api/graph";

export function useBrainGraph(project: string, limit = 400) {
  return useQuery({
    queryKey: ["brain-graph", project, limit],
    queryFn: () => getGraph(project, limit),
    refetchInterval: 5_000,
    staleTime: 2_000,
  });
}
```

- [ ] **Step 2: `ui/lib/queries/use-memory-detail.ts`**

```typescript
import { useQuery } from "@tanstack/react-query";
import { getMemoryDetail } from "@/lib/api/detail";

export function useMemoryDetail(memoryId: string | null) {
  return useQuery({
    queryKey: ["memory-detail", memoryId],
    queryFn: () => getMemoryDetail(memoryId as string),
    enabled: Boolean(memoryId),
    staleTime: 30_000,
  });
}
```

- [ ] **Step 3: `ui/lib/queries/use-kb.ts`**

```typescript
import { useQuery } from "@tanstack/react-query";
import { getKb } from "@/lib/api/kb";

export function useKb(project: string) {
  return useQuery({
    queryKey: ["kb", project],
    queryFn: () => getKb(project),
    refetchOnWindowFocus: true,
    staleTime: 60_000,
  });
}
```

- [ ] **Step 4: `ui/lib/queries/use-resume.ts`**

```typescript
import { useQuery } from "@tanstack/react-query";
import { getResume } from "@/lib/api/resume";

export function useResume(project: string) {
  return useQuery({
    queryKey: ["resume", project],
    queryFn: () => getResume(project),
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}
```

- [ ] **Step 5: `ui/lib/queries/use-pressure.ts`**

```typescript
import { useQuery } from "@tanstack/react-query";
import { getPressure } from "@/lib/api/pressure";

export function usePressure(project: string) {
  return useQuery({
    queryKey: ["pressure", project],
    queryFn: () => getPressure(project),
    staleTime: 30_000,
  });
}
```

- [ ] **Step 6: `ui/lib/queries/use-prune.ts`**

```typescript
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { postPrunePlan, postPruneApply } from "@/lib/api/prune";
import type { PrunePlan, PruneApplyResponse } from "@/lib/schemas";

export function usePrunePlanMutation() {
  return useMutation<PrunePlan, Error, { project: string; limit?: number }>({
    mutationFn: ({ project, limit }) => postPrunePlan(project, limit),
  });
}

export function usePruneApplyMutation() {
  const qc = useQueryClient();
  return useMutation<PruneApplyResponse, Error, { planId: string; confirm: string }>({
    mutationFn: ({ planId, confirm }) => postPruneApply(planId, confirm),
    onSuccess: () => {
      // Invalidate affected queries so the graph and pressure refresh
      qc.invalidateQueries({ queryKey: ["brain-graph"] });
      qc.invalidateQueries({ queryKey: ["pressure"] });
      qc.invalidateQueries({ queryKey: ["kb"] });
      qc.invalidateQueries({ queryKey: ["resume"] });
    },
  });
}
```

- [ ] **Step 7: `ui/lib/queries/use-backfill.ts`**

```typescript
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { postBackfill } from "@/lib/api/backfill";
import type { BackfillReport } from "@/lib/schemas";

export function useBackfillMutation() {
  const qc = useQueryClient();
  return useMutation<BackfillReport, Error, { dry_run: boolean; project?: string }>({
    mutationFn: (vars) => postBackfill(vars),
    onSuccess: (_data, vars) => {
      if (!vars.dry_run) {
        qc.invalidateQueries({ queryKey: ["brain-graph"] });
        qc.invalidateQueries({ queryKey: ["kb"] });
      }
    },
  });
}
```

- [ ] **Step 8: Typecheck**

```bash
cd ui && npx tsc --noEmit 2>&1 | tail -5
```

- [ ] **Step 9: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/lib/queries/
git commit -m "feat(ui): TanStack Query hooks for all 8 data surfaces

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Fixtures + schemas contract tests

**Files:**
- Create: `ui/tests/fixtures/health.json`
- Create: `ui/tests/fixtures/graph.json`
- Create: `ui/tests/fixtures/kb.json`
- Create: `ui/tests/fixtures/pressure.json`
- Create: `ui/tests/fixtures/prune-plan.json`
- Create: `ui/tests/fixtures/prune-apply.json`
- Create: `ui/tests/fixtures/backfill.json`
- Create: `ui/tests/fixtures/detail.json`
- Create: `ui/tests/fixtures/resume.json`
- Create: `ui/tests/schemas.test.ts`

The fixtures are canned JSON that matches the actual backend response shapes. The contract test parses each fixture through its matching schema.

- [ ] **Step 1: Create all fixtures**

`ui/tests/fixtures/health.json`:
```json
{
  "status": "healthy",
  "transport": "streamable-http",
  "tools_enabled": ["memory"]
}
```

`ui/tests/fixtures/graph.json`:
```json
{
  "graph": {
    "nodes": [
      { "id": "2026-04-01_decision_abc12345", "type": "decision", "content": "Use Go over Rust", "tier": "semantic", "durability": 0.85, "degree": 3 },
      { "id": "2026-04-02_note_def67890", "type": "note", "content": "Observed dedupe fires on 0.97 threshold", "tier": "working", "durability": 0.25, "degree": 1 }
    ],
    "links": [
      { "source": "2026-04-01_decision_abc12345", "target": "2026-04-02_note_def67890", "weight": 0.6, "relation": "related_to" }
    ]
  }
}
```

`ui/tests/fixtures/kb.json`:
```json
{
  "project": "test",
  "decisions": [
    { "memory_id": "d1", "type": "decision", "tier": "semantic", "date": "2026-04-01", "summary": "Use behavioral tiering, not type lookup" }
  ],
  "requirements": [
    { "memory_id": "r1", "type": "requirement", "tier": "semantic", "date": "2026-04-02", "summary": "Prune apply must be REST only" }
  ],
  "preferences": [
    { "memory_id": "p1", "type": "preference", "tier": "semantic", "date": "2026-04-03", "summary": "JR prefers terse responses" }
  ],
  "learnings": [
    { "memory_id": "l1", "type": "learning", "tier": "episodic", "date": "2026-04-04", "summary": "Dedupe threshold 0.97 is stable" }
  ]
}
```

`ui/tests/fixtures/pressure.json`:
```json
{
  "project": "test",
  "load_score": 0.12,
  "capacity": 147,
  "flagged": {
    "stale_working_count": 8,
    "low_value_count": 10,
    "contradiction_count": 1
  },
  "candidates": []
}
```

`ui/tests/fixtures/prune-plan.json`:
```json
{
  "plan_id": "b3a9e7d1c2f845e60b84c3d2a1f9e8b7",
  "project": "test",
  "generated_at": "2026-04-10T12:00:00",
  "expires_at": "2026-04-10T12:15:00",
  "summary": "2 candidates (max 200)",
  "candidates": [
    { "memory_id": "w1", "tier": "working", "reason": "tier=working salience=0.10 age=30d", "age_days": 30, "salience": 0.1 },
    { "memory_id": "w2", "tier": "working", "reason": "tier=working salience=0.15 age=22d", "age_days": 22, "salience": 0.15 }
  ]
}
```

`ui/tests/fixtures/prune-apply.json`:
```json
{
  "plan_id": "b3a9e7d1c2f845e60b84c3d2a1f9e8b7",
  "deleted": ["w1", "w2"],
  "skipped": []
}
```

`ui/tests/fixtures/backfill.json`:
```json
{
  "dry_run": true,
  "project": null,
  "updated_by_tier": { "working": 42, "episodic": 8, "semantic": 3, "identity": 0 },
  "skipped": [],
  "errors": [],
  "total": 53
}
```

`ui/tests/fixtures/detail.json`:
```json
{
  "memory": {
    "memory_id": "2026-04-01_decision_abc12345",
    "content": "Use Go over Rust for the backend rewrite because team familiarity",
    "type": "decision",
    "tier": "semantic",
    "durability": 0.85,
    "reinforcement_count": 3,
    "date": "2026-04-01",
    "project": "test",
    "salience": 0.8
  },
  "neighbors": [
    {
      "relation": "related_to",
      "memory": {
        "memory_id": "2026-04-02_note_def67890",
        "content": "Go tooling is more mature",
        "type": "note",
        "tier": "working",
        "date": "2026-04-02",
        "project": "test"
      }
    }
  ],
  "scope": {
    "project": "test",
    "agent": "claude-code",
    "repo_name": "memento-mcp"
  }
}
```

`ui/tests/fixtures/resume.json`:
```json
{
  "scope": { "project": "test", "agent": "claude-code" },
  "recent": [],
  "important": [],
  "unresolved": [],
  "next_steps": [],
  "handoff": "## Test project\n- Recent: 0\n- Important: 0\n",
  "pressure": { "low_value_count": 0, "stale_working_count": 0, "candidates": [] },
  "pressure_report": "# Memory Pressure Report\n\n- low_value_count: 0\n- stale_working_count: 0\n\nNo cleanup pressure detected.\n",
  "truncated": false,
  "summary": "Test project resume"
}
```

- [ ] **Step 2: Create `ui/tests/schemas.test.ts`**

```typescript
import { describe, test, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

import {
  HealthSchema,
  GraphResponseSchema,
  KbResponseSchema,
  PressureResponseSchema,
  PrunePlanSchema,
  PruneApplyResponseSchema,
  BackfillReportSchema,
  DetailResponseSchema,
  ResumeResponseSchema,
} from "@/lib/schemas";

const FIXTURES = path.join(__dirname, "fixtures");

function load(name: string): unknown {
  return JSON.parse(fs.readFileSync(path.join(FIXTURES, name), "utf-8"));
}

describe("schemas parse real fixtures", () => {
  test("HealthSchema", () => {
    expect(HealthSchema.parse(load("health.json"))).toMatchObject({ status: "healthy" });
  });

  test("GraphResponseSchema", () => {
    const parsed = GraphResponseSchema.parse(load("graph.json"));
    expect(parsed.graph?.nodes.length).toBe(2);
    expect(parsed.graph?.links.length).toBe(1);
  });

  test("KbResponseSchema", () => {
    const parsed = KbResponseSchema.parse(load("kb.json"));
    expect(parsed.decisions.length).toBe(1);
    expect(parsed.requirements.length).toBe(1);
    expect(parsed.preferences.length).toBe(1);
    expect(parsed.learnings.length).toBe(1);
  });

  test("PressureResponseSchema", () => {
    const parsed = PressureResponseSchema.parse(load("pressure.json"));
    expect(parsed.flagged.stale_working_count).toBe(8);
  });

  test("PrunePlanSchema", () => {
    const parsed = PrunePlanSchema.parse(load("prune-plan.json"));
    expect(parsed.candidates.length).toBe(2);
    expect(parsed.plan_id).toHaveLength(32);
  });

  test("PruneApplyResponseSchema", () => {
    expect(PruneApplyResponseSchema.parse(load("prune-apply.json")).deleted).toEqual(["w1", "w2"]);
  });

  test("BackfillReportSchema", () => {
    expect(BackfillReportSchema.parse(load("backfill.json")).total).toBe(53);
  });

  test("DetailResponseSchema", () => {
    const parsed = DetailResponseSchema.parse(load("detail.json"));
    expect(parsed.memory?.memory_id).toBe("2026-04-01_decision_abc12345");
    expect(parsed.neighbors.length).toBe(1);
  });

  test("ResumeResponseSchema", () => {
    expect(ResumeResponseSchema.parse(load("resume.json")).truncated).toBe(false);
  });
});
```

- [ ] **Step 3: Run the contract tests**

```bash
cd ui && npm test -- schemas 2>&1 | tail -20
```

Expected: 9/9 pass.

- [ ] **Step 4: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/tests/fixtures/ ui/tests/schemas.test.ts
git commit -m "test(ui): Zod contract tests against real endpoint fixtures

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Phase D — Brain Surface (Tasks 13-16)

### Task 13: BrainScene (aurora + starfield background)

**Files:**
- Create: `ui/components/brain/brain-scene.tsx`

- [ ] **Step 1: Create the brain scene**

```typescript
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
```

- [ ] **Step 2: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/components/brain/brain-scene.tsx
git commit -m "feat(ui): BrainScene — aurora mesh gradient + starfield background

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: BrainCanvas (react-force-graph wrapper)

**Files:**
- Create: `ui/components/brain/brain-canvas.tsx`
- Create: `ui/tests/brain-canvas.test.tsx`

- [ ] **Step 1: Write failing test**

`ui/tests/brain-canvas.test.tsx`:
```typescript
import { describe, test, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import { BrainCanvas } from "@/components/brain/brain-canvas";

// Mock react-force-graph-2d: it uses canvas APIs that jsdom does not provide.
// Replace with a stub that exposes onNodeClick as a plain div we can interact with.
vi.mock("react-force-graph-2d", () => ({
  default: (props: any) => (
    <div
      data-testid="force-graph-2d"
      onClick={() => props.onNodeClick?.({ id: "m1" })}
    >
      mock-force-graph
    </div>
  ),
}));

describe("BrainCanvas", () => {
  test("renders without crashing on empty graph", () => {
    const { container } = render(<BrainCanvas nodes={[]} links={[]} onNodeClick={vi.fn()} />);
    expect(container).toBeTruthy();
  });

  test("calls onNodeClick with memory id when a node is clicked", async () => {
    const handler = vi.fn();
    const { getByTestId } = render(
      <BrainCanvas
        nodes={[{ id: "m1", type: "decision", content: "test", tier: "semantic" }]}
        links={[]}
        onNodeClick={handler}
      />
    );
    getByTestId("force-graph-2d").click();
    expect(handler).toHaveBeenCalledWith("m1");
  });
});
```

- [ ] **Step 2: Run the test — expect failure**

```bash
cd ui && npm test -- brain-canvas 2>&1 | tail -15
```

Expected: `Cannot find module '@/components/brain/brain-canvas'`.

- [ ] **Step 3: Create `ui/components/brain/brain-canvas.tsx`**

```typescript
"use client";

import { useRef, useMemo } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { typeColor, tierColor } from "@/lib/theme";
import type { GraphNode, GraphLink } from "@/lib/schemas";

type Props = {
  nodes: GraphNode[];
  links: GraphLink[];
  selectedId?: string | null;
  onNodeClick: (memoryId: string) => void;
};

type GraphNodeWithVisuals = GraphNode & {
  __color: string;
  __size: number;
};

export function BrainCanvas({ nodes, links, selectedId, onNodeClick }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);

  const enriched = useMemo<GraphNodeWithVisuals[]>(
    () =>
      nodes.map((n) => ({
        ...n,
        __color: typeColor(n.type),
        __size: 4 + Math.min(n.durability ?? 0, 1) * 10,
      })),
    [nodes]
  );

  return (
    <div ref={containerRef} className="h-full w-full">
      <ForceGraph2D
        graphData={{ nodes: enriched as object[], links: links as object[] }}
        backgroundColor="rgba(0,0,0,0)"
        nodeRelSize={4}
        linkWidth={(l: any) => 0.5 + (l.weight ?? 0) * 1.5}
        linkColor={(l: any) => {
          if (l.relation === "contradicts") return "rgba(248, 113, 113, 0.6)";
          if (l.relation === "supersedes") return "rgba(96, 165, 250, 0.5)";
          return "rgba(148, 163, 184, 0.35)";
        }}
        nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D, scale: number) => {
          const r = node.__size / scale + 2;
          ctx.beginPath();
          ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
          ctx.fillStyle = node.__color ?? "#94a3b8";
          ctx.shadowColor = node.__color ?? "#94a3b8";
          ctx.shadowBlur = 14;
          ctx.fill();
          ctx.shadowBlur = 0;

          if (node.id === selectedId) {
            ctx.beginPath();
            ctx.arc(node.x, node.y, r + 4, 0, Math.PI * 2);
            ctx.strokeStyle = "#f8fafc";
            ctx.lineWidth = 1.5;
            ctx.stroke();
          }

          if (node.tier && node.tier !== "working") {
            ctx.beginPath();
            ctx.arc(node.x, node.y, r + 2, 0, Math.PI * 2);
            ctx.strokeStyle = tierColor(node.tier);
            ctx.lineWidth = 0.8;
            ctx.stroke();
          }
        }}
        onNodeClick={(node: any) => {
          if (node?.id) onNodeClick(String(node.id));
        }}
        cooldownTicks={100}
      />
    </div>
  );
}
```

- [ ] **Step 4: Re-run the test**

```bash
cd ui && npm test -- brain-canvas 2>&1 | tail -15
```

Expected: 2/2 pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/components/brain/brain-canvas.tsx ui/tests/brain-canvas.test.tsx
git commit -m "feat(ui): BrainCanvas — force-directed graph with tier/type encoding

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 15: NodeDrawer + legends + graph stats

**Files:**
- Create: `ui/components/brain/node-drawer.tsx`
- Create: `ui/components/brain/tier-legend.tsx`
- Create: `ui/components/brain/type-legend.tsx`
- Create: `ui/components/brain/graph-stats.tsx`
- Create: `ui/tests/node-drawer.test.tsx`

- [ ] **Step 1: Write failing test**

`ui/tests/node-drawer.test.tsx`:
```typescript
import { describe, test, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NodeDrawer } from "@/components/brain/node-drawer";
import type { DetailResponse } from "@/lib/schemas";

const fakeDetail: DetailResponse = {
  memory: {
    memory_id: "m1",
    content: "Use Go over Rust for the backend rewrite",
    type: "decision",
    tier: "semantic",
    durability: 0.85,
    date: "2026-04-01",
    project: "test",
    reinforcement_count: 3,
  },
  neighbors: [
    {
      relation: "related_to",
      memory: {
        memory_id: "m2",
        content: "Go tooling is more mature",
        type: "note",
        tier: "working",
      },
    },
  ],
  scope: { project: "test", agent: "claude-code", repo_name: null },
};

describe("NodeDrawer", () => {
  test("renders memory content, type/tier badges, and neighbor", () => {
    render(<NodeDrawer open detail={fakeDetail} isLoading={false} onClose={vi.fn()} />);
    expect(screen.getByText(/use go over rust/i)).toBeInTheDocument();
    expect(screen.getByText(/decision/i)).toBeInTheDocument();
    expect(screen.getByText(/semantic/i)).toBeInTheDocument();
    expect(screen.getByText(/go tooling is more mature/i)).toBeInTheDocument();
  });

  test("closes on ESC", async () => {
    const onClose = vi.fn();
    render(<NodeDrawer open detail={fakeDetail} isLoading={false} onClose={onClose} />);
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run — expect fail**

```bash
cd ui && npm test -- node-drawer 2>&1 | tail -15
```

- [ ] **Step 3: `ui/components/brain/node-drawer.tsx`**

```typescript
"use client";

import { Drawer } from "@/components/ui/drawer";
import { Badge } from "@/components/ui/badge";
import { MonoLabel } from "@/components/ui/mono-label";
import { SerifHeading } from "@/components/ui/serif-heading";
import { Skeleton } from "@/components/ui/skeleton";
import { AlertTriangle } from "lucide-react";
import type { DetailResponse } from "@/lib/schemas";

type Props = {
  open: boolean;
  detail: DetailResponse | undefined;
  isLoading: boolean;
  onClose: () => void;
};

export function NodeDrawer({ open, detail, isLoading, onClose }: Props) {
  const memory = detail?.memory;
  const hasContradicts =
    detail?.neighbors.some((n) => n.relation === "contradicts") ?? false;

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={
        isLoading || !memory ? (
          <Skeleton className="h-6 w-48" />
        ) : (
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
              {memory.type ? <Badge kind="type" value={memory.type} /> : null}
              {memory.tier ? <Badge kind="tier" value={memory.tier} /> : null}
            </div>
            <MonoLabel>{memory.memory_id}</MonoLabel>
          </div>
        )
      }
    >
      {isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-8 w-3/4" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : memory ? (
        <div className="space-y-5">
          <SerifHeading title={memory.content?.slice(0, 120) ?? ""} size="section" />
          <p className="text-sm leading-relaxed text-[var(--fg)]">{memory.content}</p>

          <div className="grid grid-cols-2 gap-3 border-y border-[var(--border)] py-3 font-mono text-xs">
            <div><MonoLabel>date</MonoLabel> <div className="text-[var(--fg)]">{memory.date ?? "—"}</div></div>
            <div><MonoLabel>durability</MonoLabel> <div className="text-[var(--fg)]">{(memory.durability ?? 0).toFixed(2)}</div></div>
            <div><MonoLabel>reinforced</MonoLabel> <div className="text-[var(--fg)]">{memory.reinforcement_count ?? 0}×</div></div>
            <div><MonoLabel>salience</MonoLabel> <div className="text-[var(--fg)]">{memory.salience !== undefined ? memory.salience.toFixed(2) : "—"}</div></div>
          </div>

          {hasContradicts ? (
            <div className="flex items-start gap-2 rounded-md border border-[var(--accent-danger)]/40 bg-[var(--accent-danger)]/10 p-3">
              <AlertTriangle size={16} className="mt-0.5 shrink-0 text-[var(--accent-danger)]" />
              <p className="text-xs text-[var(--fg)]">This memory has contradicting neighbors.</p>
            </div>
          ) : null}

          {detail?.neighbors?.length ? (
            <section>
              <MonoLabel>neighbors · {detail.neighbors.length}</MonoLabel>
              <ul className="mt-2 space-y-2">
                {detail.neighbors.map((n, i) => (
                  <li
                    key={`${n.memory.memory_id}-${i}`}
                    className="rounded-md border border-[var(--border)] bg-[var(--surface-0)] p-3"
                  >
                    <div className="mb-1 flex items-center gap-2">
                      <Badge kind="type" value={n.memory.type ?? "note"} />
                      <MonoLabel>{n.relation}</MonoLabel>
                    </div>
                    <p className="text-xs text-[var(--fg-muted)]">{n.memory.content}</p>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      ) : (
        <p className="text-sm text-[var(--fg-muted)]">Memory not found.</p>
      )}
    </Drawer>
  );
}
```

- [ ] **Step 4: `ui/components/brain/type-legend.tsx`**

```typescript
import { MonoLabel } from "@/components/ui/mono-label";
import { tokens } from "@/lib/theme";

const TYPES = ["decision", "requirement", "preference", "learning", "fact", "note"] as const;

export function TypeLegend() {
  return (
    <div className="flex items-center gap-3 rounded-full border border-[var(--border)] bg-[var(--bg-frost)] px-3 py-1.5 backdrop-blur-[12px]">
      <MonoLabel>types</MonoLabel>
      {TYPES.map((t) => (
        <span key={t} className="flex items-center gap-1 text-[11px] text-[var(--fg-muted)]">
          <span className="h-2 w-2 rounded-full" style={{ background: (tokens.type as Record<string, string>)[t] }} />
          {t}
        </span>
      ))}
    </div>
  );
}
```

- [ ] **Step 5: `ui/components/brain/tier-legend.tsx`**

```typescript
import { MonoLabel } from "@/components/ui/mono-label";
import { tokens } from "@/lib/theme";

const TIERS = ["identity", "semantic", "episodic", "working"] as const;

export function TierLegend() {
  return (
    <div className="flex items-center gap-3 rounded-full border border-[var(--border)] bg-[var(--bg-frost)] px-3 py-1.5 backdrop-blur-[12px]">
      <MonoLabel>tiers</MonoLabel>
      {TIERS.map((t) => (
        <span key={t} className="flex items-center gap-1 text-[11px] text-[var(--fg-muted)]">
          <span
            className="h-2 w-2 rounded-full"
            style={{ background: (tokens.tier as Record<string, string>)[t], boxShadow: `0 0 6px ${(tokens.tier as Record<string, string>)[t]}` }}
          />
          {t}
        </span>
      ))}
    </div>
  );
}
```

- [ ] **Step 6: `ui/components/brain/graph-stats.tsx`**

```typescript
import { MonoLabel } from "@/components/ui/mono-label";

type Props = {
  nodeCount: number;
  linkCount: number;
  refreshedAt: string;
};

export function GraphStats({ nodeCount, linkCount, refreshedAt }: Props) {
  return (
    <div className="flex items-center gap-4 rounded-full border border-[var(--border)] bg-[var(--bg-frost)] px-4 py-1.5 backdrop-blur-[12px]">
      <MonoLabel>{nodeCount} nodes</MonoLabel>
      <MonoLabel>{linkCount} edges</MonoLabel>
      <MonoLabel>refreshed {refreshedAt}</MonoLabel>
    </div>
  );
}
```

- [ ] **Step 7: Run tests**

```bash
cd ui && npm test -- node-drawer 2>&1 | tail -15
```

Expected: 2/2 pass.

- [ ] **Step 8: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/components/brain/node-drawer.tsx ui/components/brain/tier-legend.tsx ui/components/brain/type-legend.tsx ui/components/brain/graph-stats.tsx ui/tests/node-drawer.test.tsx
git commit -m "feat(ui): NodeDrawer with details + neighbors, tier/type legends, graph stats

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 16: /brain/page.tsx wiring

**Files:**
- Rewrite: `ui/app/brain/page.tsx`

- [ ] **Step 1: Replace the stub page**

```typescript
"use client";

import { useState } from "react";
import { BrainScene } from "@/components/brain/brain-scene";
import { BrainCanvas } from "@/components/brain/brain-canvas";
import { NodeDrawer } from "@/components/brain/node-drawer";
import { TypeLegend } from "@/components/brain/type-legend";
import { TierLegend } from "@/components/brain/tier-legend";
import { GraphStats } from "@/components/brain/graph-stats";
import { Empty } from "@/components/ui/empty";
import { useBrainGraph } from "@/lib/queries/use-brain-graph";
import { useMemoryDetail } from "@/lib/queries/use-memory-detail";
import { useProjectStore } from "@/lib/project-store";
import type { GraphNode, GraphLink } from "@/lib/schemas";

export default function BrainPage() {
  const project = useProjectStore((s) => s.project);
  const { data, dataUpdatedAt, isLoading } = useBrainGraph(project);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const detail = useMemoryDetail(selectedId);

  const nodes = (data?.graph?.nodes ?? []) as GraphNode[];
  const links = (data?.graph?.links ?? []) as GraphLink[];
  const refreshedAt = dataUpdatedAt ? new Date(dataUpdatedAt).toLocaleTimeString() : "…";

  return (
    <div className="relative h-[calc(100vh-3.5rem)] w-full">
      <BrainScene>
        {nodes.length === 0 && !isLoading ? (
          <div className="flex h-full items-center justify-center">
            <Empty title="No memories in this project yet" hint="Try observe() from your agent" />
          </div>
        ) : (
          <BrainCanvas nodes={nodes} links={links} selectedId={selectedId} onNodeClick={setSelectedId} />
        )}
      </BrainScene>

      <div className="pointer-events-none absolute right-6 top-6 flex justify-end">
        <div className="pointer-events-auto">
          <GraphStats nodeCount={nodes.length} linkCount={links.length} refreshedAt={refreshedAt} />
        </div>
      </div>

      <div className="pointer-events-none absolute bottom-6 left-6 flex flex-col gap-2">
        <div className="pointer-events-auto"><TypeLegend /></div>
        <div className="pointer-events-auto"><TierLegend /></div>
      </div>

      <NodeDrawer
        open={selectedId !== null}
        detail={detail.data}
        isLoading={detail.isLoading}
        onClose={() => setSelectedId(null)}
      />
    </div>
  );
}
```

- [ ] **Step 2: Run the dev server + backend and manually verify the brain loads**

Optional manual check — not blocking the commit since we have unit tests for the components.

- [ ] **Step 3: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/app/brain/page.tsx
git commit -m "feat(ui): wire Brain surface — graph, drawer, legends, stats

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Phase E — KB + Continuity (Tasks 17-21)

### Task 17: KB components

**Files:**
- Create: `ui/components/kb/kb-columns.tsx`
- Create: `ui/components/kb/kb-slice.tsx`
- Create: `ui/components/kb/kb-entry.tsx`
- Create: `ui/components/kb/kb-empty.tsx`
- Create: `ui/tests/kb-columns.test.tsx`

- [ ] **Step 1: Write failing test**

```typescript
import { describe, test, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { KbColumns } from "@/components/kb/kb-columns";
import kbFixture from "./fixtures/kb.json";
import { KbResponseSchema } from "@/lib/schemas";

describe("KbColumns", () => {
  test("renders four slice headers and their counts", () => {
    const data = KbResponseSchema.parse(kbFixture);
    render(<KbColumns data={data} />);
    expect(screen.getByRole("heading", { name: /decisions/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /requirements/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /preferences/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /learnings/i })).toBeInTheDocument();
  });

  test("renders entries from fixture", () => {
    const data = KbResponseSchema.parse(kbFixture);
    render(<KbColumns data={data} />);
    expect(screen.getByText(/behavioral tiering/i)).toBeInTheDocument();
    expect(screen.getByText(/terse responses/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: `ui/components/kb/kb-empty.tsx`**

```typescript
export function KbEmpty({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center gap-1 py-8 text-center">
      <span className="font-serif text-3xl text-[var(--fg-dim)]">—</span>
      <p className="text-xs text-[var(--fg-dim)]">no {label} yet</p>
    </div>
  );
}
```

- [ ] **Step 3: `ui/components/kb/kb-entry.tsx`**

```typescript
"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { MonoLabel } from "@/components/ui/mono-label";
import { Badge } from "@/components/ui/badge";
import type { KbEntry as KbEntryType } from "@/lib/schemas";

type Props = {
  entry: KbEntryType;
};

export function KbEntry({ entry }: Props) {
  const [open, setOpen] = useState(false);
  return (
    <li className="border-b border-[var(--border)] last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-start gap-3 px-1 py-3 text-left transition-colors hover:bg-[var(--surface-0)]"
        aria-expanded={open}
      >
        <ChevronRight
          size={14}
          className={`mt-0.5 shrink-0 text-[var(--fg-dim)] transition-transform ${open ? "rotate-90" : ""}`}
        />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <MonoLabel>{entry.date ?? "—"}</MonoLabel>
          <p className="text-sm text-[var(--fg)]">{entry.summary}</p>
          {open && entry.content ? (
            <div className="mt-2 space-y-2 rounded-md border border-[var(--border)] bg-[var(--surface-0)] p-3">
              <p className="text-sm leading-relaxed text-[var(--fg)]">{entry.content}</p>
              <div className="flex items-center gap-2">
                {entry.tier ? <Badge kind="tier" value={entry.tier} /> : null}
                {entry.type ? <Badge kind="type" value={entry.type} /> : null}
              </div>
            </div>
          ) : null}
        </div>
      </button>
    </li>
  );
}
```

- [ ] **Step 4: `ui/components/kb/kb-slice.tsx`**

```typescript
import { KbEntry } from "./kb-entry";
import { KbEmpty } from "./kb-empty";
import { MonoLabel } from "@/components/ui/mono-label";
import type { KbEntry as KbEntryType } from "@/lib/schemas";

type Props = {
  title: string;
  accentVar: string; // e.g. "var(--accent-warning)"
  entries: KbEntryType[];
};

export function KbSlice({ title, accentVar, entries }: Props) {
  return (
    <section
      className="flex min-w-0 flex-col rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-elevated)]"
      style={{ borderLeft: `3px solid ${accentVar}` }}
    >
      <header className="flex items-baseline justify-between gap-3 border-b border-[var(--border)] px-5 py-4">
        <h2 className="font-serif text-xl">{title}</h2>
        <MonoLabel>{entries.length}</MonoLabel>
      </header>
      <div className="flex-1 overflow-y-auto px-4">
        {entries.length === 0 ? (
          <KbEmpty label={title.toLowerCase()} />
        ) : (
          <ul>
            {entries.map((e) => (
              <KbEntry key={e.memory_id ?? e.summary} entry={e} />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
```

- [ ] **Step 5: `ui/components/kb/kb-columns.tsx`**

```typescript
import { KbSlice } from "./kb-slice";
import type { KbResponse } from "@/lib/schemas";

type Props = {
  data: KbResponse;
};

export function KbColumns({ data }: Props) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
      <KbSlice title="Decisions" accentVar="var(--accent-warning)" entries={data.decisions} />
      <KbSlice title="Requirements" accentVar="var(--accent-danger)" entries={data.requirements} />
      <KbSlice title="Preferences" accentVar="var(--accent-secondary)" entries={data.preferences} />
      <KbSlice title="Learnings" accentVar="var(--accent-success)" entries={data.learnings} />
    </div>
  );
}
```

- [ ] **Step 6: Run tests**

```bash
cd ui && npm test -- kb 2>&1 | tail -15
```

- [ ] **Step 7: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/components/kb/ ui/tests/kb-columns.test.tsx
git commit -m "feat(ui): KB components — 4-column typed slices with expandable entries

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 18: /kb/page.tsx wiring

**Files:**
- Rewrite: `ui/app/kb/page.tsx`

- [ ] **Step 1: Replace the stub**

```typescript
"use client";

import { KbColumns } from "@/components/kb/kb-columns";
import { SerifHeading } from "@/components/ui/serif-heading";
import { Empty } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { useKb } from "@/lib/queries/use-kb";
import { useProjectStore } from "@/lib/project-store";

export default function KbPage() {
  const project = useProjectStore((s) => s.project);
  const { data, isLoading, isError } = useKb(project);

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <SerifHeading eyebrow="CURATED BY TYPE · LIVE" title={`Knowledge Base · ${project}`} />
      {isLoading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-96 w-full" />
          ))}
        </div>
      ) : isError || !data ? (
        <Empty title="Could not load knowledge base" hint="Check backend connection" />
      ) : (
        <KbColumns data={data} />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/app/kb/page.tsx
git commit -m "feat(ui): wire KB surface — 4 typed slices from /api/memory/kb

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 19: Continuity components

**Files:**
- Create: `ui/components/continuity/resume-header.tsx`
- Create: `ui/components/continuity/important-section.tsx`
- Create: `ui/components/continuity/recent-section.tsx`
- Create: `ui/components/continuity/next-steps-list.tsx`
- Create: `ui/components/continuity/conflicts-panel.tsx`
- Create: `ui/components/continuity/truncated-warning.tsx`
- Create: `ui/tests/continuity.test.tsx`

- [ ] **Step 1: Write failing test**

```typescript
import { describe, test, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TruncatedWarning } from "@/components/continuity/truncated-warning";
import { ResumeHeader } from "@/components/continuity/resume-header";

describe("Continuity — TruncatedWarning", () => {
  test("renders warning text when truncated", () => {
    render(<TruncatedWarning truncated={true} />);
    expect(screen.getByText(/showing/i)).toBeInTheDocument();
  });

  test("renders nothing when not truncated", () => {
    const { container } = render(<TruncatedWarning truncated={false} />);
    expect(container.firstChild).toBeNull();
  });
});

describe("Continuity — ResumeHeader", () => {
  test("renders scope metadata as mono", () => {
    const scope = { project: "test", agent: "claude-code", repo_name: "memento-mcp", branch: "feat/x" };
    render(<ResumeHeader scope={scope} />);
    expect(screen.getByText(/claude-code/i)).toBeInTheDocument();
    expect(screen.getByText(/memento-mcp/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: `ui/components/continuity/truncated-warning.tsx`**

```typescript
import { AlertTriangle } from "lucide-react";

export function TruncatedWarning({ truncated }: { truncated: boolean }) {
  if (!truncated) return null;
  return (
    <div className="flex items-start gap-3 rounded-md border border-[var(--accent-warning)]/40 bg-[var(--accent-warning)]/10 p-4">
      <AlertTriangle size={18} className="mt-0.5 shrink-0 text-[var(--accent-warning)]" />
      <div>
        <p className="text-sm font-medium text-[var(--fg)]">Showing recent window</p>
        <p className="mt-1 text-xs text-[var(--fg-muted)]">
          This project exceeds the bounded scroll cap. You are seeing the most recent slice, not
          the full set.
        </p>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: `ui/components/continuity/resume-header.tsx`**

```typescript
import { MonoLabel } from "@/components/ui/mono-label";
import { Card } from "@/components/ui/card";

type Props = {
  scope: Record<string, unknown>;
};

const FIELDS: Array<[string, string]> = [
  ["project", "project"],
  ["agent", "agent"],
  ["repo_name", "repo"],
  ["branch", "branch"],
  ["trust_boundary", "trust"],
];

export function ResumeHeader({ scope }: Props) {
  return (
    <Card variant="glass">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
        {FIELDS.map(([key, label]) => {
          const value = scope[key];
          if (!value) return null;
          return (
            <div key={key}>
              <MonoLabel>{label}</MonoLabel>
              <div className="mt-1 font-mono text-sm text-[var(--fg)]">{String(value)}</div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
```

- [ ] **Step 4: `ui/components/continuity/important-section.tsx`**

```typescript
import { SerifHeading } from "@/components/ui/serif-heading";
import { Badge } from "@/components/ui/badge";
import { MonoLabel } from "@/components/ui/mono-label";
import { Empty } from "@/components/ui/empty";

type ImportantItem = {
  memory_id: string;
  content: string;
  type?: string;
  tier?: string;
  date?: string;
  importance?: number;
};

export function ImportantSection({ items }: { items: ImportantItem[] }) {
  return (
    <section className="space-y-3">
      <SerifHeading title="Important" size="section" eyebrow="HIGH-SIGNAL MEMORIES" />
      {items.length === 0 ? (
        <Empty title="Nothing important yet" />
      ) : (
        <ul className="space-y-2">
          {items.map((item) => (
            <li
              key={item.memory_id}
              className="rounded-md border border-[var(--border)] bg-[var(--bg-elevated)] p-4"
            >
              <div className="mb-2 flex items-center gap-2">
                {item.type ? <Badge kind="type" value={item.type} /> : null}
                {item.tier ? <Badge kind="tier" value={item.tier} /> : null}
                <MonoLabel>{item.date ?? ""}</MonoLabel>
              </div>
              <p className="font-serif text-base leading-snug text-[var(--fg)]">{item.content}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
```

- [ ] **Step 5: `ui/components/continuity/recent-section.tsx`**

```typescript
import { SerifHeading } from "@/components/ui/serif-heading";
import { MonoLabel } from "@/components/ui/mono-label";
import { Empty } from "@/components/ui/empty";

type RecentItem = {
  memory_id: string;
  content: string;
  date?: string;
  type?: string;
};

export function RecentSection({ items }: { items: RecentItem[] }) {
  return (
    <section className="space-y-3">
      <SerifHeading title="Recent" size="section" eyebrow="MOST RECENT BY DATE" />
      {items.length === 0 ? (
        <Empty title="No recent activity" />
      ) : (
        <ol className="relative space-y-4 border-l border-[var(--border)] pl-4">
          {items.map((item) => (
            <li key={item.memory_id} className="relative">
              <span
                className="absolute -left-[22px] top-1.5 h-2 w-2 rounded-full bg-[var(--accent-primary)]"
                style={{ boxShadow: "0 0 8px var(--accent-primary)" }}
              />
              <MonoLabel>{item.date ?? ""}</MonoLabel>
              <p className="mt-1 text-sm text-[var(--fg)]">{item.content}</p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
```

- [ ] **Step 6: `ui/components/continuity/next-steps-list.tsx`**

```typescript
import { SerifHeading } from "@/components/ui/serif-heading";
import { Empty } from "@/components/ui/empty";

export function NextStepsList({ steps }: { steps: unknown[] }) {
  if (steps.length === 0) {
    return <Empty title="No extracted next steps" />;
  }
  return (
    <section className="space-y-3">
      <SerifHeading title="Next Steps" size="section" eyebrow="WHAT TO DO NEXT" />
      <ul className="space-y-2">
        {steps.map((s, i) => (
          <li
            key={i}
            className="rounded-md border border-[var(--border)] bg-[var(--bg-elevated)] p-3 font-serif text-base text-[var(--fg)]"
          >
            {typeof s === "string" ? s : JSON.stringify(s)}
          </li>
        ))}
      </ul>
    </section>
  );
}
```

- [ ] **Step 7: `ui/components/continuity/conflicts-panel.tsx`**

```typescript
import { AlertTriangle } from "lucide-react";
import { SerifHeading } from "@/components/ui/serif-heading";
import { MonoLabel } from "@/components/ui/mono-label";

type Conflict = { memory_id: string; conflicts_with: string; content?: string };

export function ConflictsPanel({ conflicts }: { conflicts: Conflict[] }) {
  return (
    <section className="space-y-3">
      <SerifHeading title="Unresolved" size="section" eyebrow="CONTRADICTIONS" />
      {conflicts.length === 0 ? (
        <div className="rounded-md border border-[var(--accent-success)]/30 bg-[var(--accent-success)]/10 p-4 font-serif text-sm text-[var(--fg)]">
          All clear.
        </div>
      ) : (
        <ul className="space-y-2">
          {conflicts.map((c, i) => (
            <li
              key={`${c.memory_id}-${i}`}
              className="flex items-start gap-3 rounded-md border border-[var(--accent-danger)]/40 bg-[var(--accent-danger)]/10 p-3"
            >
              <AlertTriangle size={14} className="mt-0.5 shrink-0 text-[var(--accent-danger)]" />
              <div className="flex-1">
                <MonoLabel>{c.memory_id} ↔ {c.conflicts_with}</MonoLabel>
                {c.content ? <p className="mt-1 text-xs text-[var(--fg-muted)]">{c.content}</p> : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
```

- [ ] **Step 8: Run tests**

```bash
cd ui && npm test -- continuity 2>&1 | tail -15
```

- [ ] **Step 9: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/components/continuity/ ui/tests/continuity.test.tsx
git commit -m "feat(ui): Continuity components — resume header, important/recent, next steps, conflicts

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 20: /continuity/page.tsx wiring

**Files:**
- Rewrite: `ui/app/continuity/page.tsx`

- [ ] **Step 1: Replace the stub**

```typescript
"use client";

import { SerifHeading } from "@/components/ui/serif-heading";
import { Skeleton } from "@/components/ui/skeleton";
import { Empty } from "@/components/ui/empty";
import { ResumeHeader } from "@/components/continuity/resume-header";
import { ImportantSection } from "@/components/continuity/important-section";
import { RecentSection } from "@/components/continuity/recent-section";
import { NextStepsList } from "@/components/continuity/next-steps-list";
import { ConflictsPanel } from "@/components/continuity/conflicts-panel";
import { TruncatedWarning } from "@/components/continuity/truncated-warning";
import { useResume } from "@/lib/queries/use-resume";
import { useProjectStore } from "@/lib/project-store";

export default function ContinuityPage() {
  const project = useProjectStore((s) => s.project);
  const { data, isLoading, isError } = useResume(project);

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <SerifHeading eyebrow="WHAT TO LOAD ON SESSION START" title={`Continuity · ${project}`} />

      {isLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-24 w-full" />
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <Skeleton className="h-64 w-full" />
            <Skeleton className="h-64 w-full" />
            <Skeleton className="h-64 w-full" />
          </div>
        </div>
      ) : isError || !data ? (
        <Empty title="Could not load continuity" hint="Check backend connection" />
      ) : (
        <>
          <TruncatedWarning truncated={data.truncated} />
          <ResumeHeader scope={data.scope} />
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
            <ImportantSection items={data.important as any} />
            <RecentSection items={data.recent as any} />
            <ConflictsPanel conflicts={data.unresolved as any} />
          </div>
          <NextStepsList steps={data.next_steps} />
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/app/continuity/page.tsx
git commit -m "feat(ui): wire Continuity surface — resume, important/recent, conflicts, next steps

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Phase F — Hygiene (the keystone) (Tasks 21-28)

### Task 21: PressureGauges + PressureExplainer

**Files:**
- Create: `ui/components/hygiene/pressure-gauges.tsx`
- Create: `ui/components/hygiene/pressure-explainer.tsx`
- Create: `ui/tests/pressure-gauges.test.tsx`

- [ ] **Step 1: Write failing test**

```typescript
import { describe, test, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PressureGauges } from "@/components/hygiene/pressure-gauges";
import pressureFixture from "./fixtures/pressure.json";
import { PressureResponseSchema } from "@/lib/schemas";

describe("PressureGauges", () => {
  test("renders load, capacity, flagged from fixture", () => {
    const data = PressureResponseSchema.parse(pressureFixture);
    render(<PressureGauges data={data} />);
    expect(screen.getByText(/147/)).toBeInTheDocument(); // capacity
    expect(screen.getByText(/0.12/)).toBeInTheDocument(); // load score
  });
});
```

- [ ] **Step 2: `ui/components/hygiene/pressure-gauges.tsx`**

```typescript
import { MonoLabel } from "@/components/ui/mono-label";
import { Card } from "@/components/ui/card";
import type { PressureResponse } from "@/lib/schemas";

type Props = { data: PressureResponse };

function GaugeBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = Math.max(0, Math.min((value / max) * 100, 100));
  return (
    <div
      role="meter"
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={max}
      className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--surface-1)]"
    >
      <div
        className="h-full rounded-full transition-[width] duration-[var(--dur-med)]"
        style={{ width: `${pct}%`, background: color, boxShadow: `0 0 8px ${color}` }}
      />
    </div>
  );
}

export function PressureGauges({ data }: Props) {
  const totalFlagged =
    data.flagged.stale_working_count + data.flagged.low_value_count + data.flagged.contradiction_count;
  return (
    <Card variant="flat" className="grid grid-cols-1 gap-6 md:grid-cols-3">
      <div className="space-y-2">
        <MonoLabel>load score</MonoLabel>
        <div className="font-mono text-3xl text-[var(--fg)]">{data.load_score.toFixed(2)}</div>
        <GaugeBar value={data.load_score} max={1} color="var(--accent-primary)" />
      </div>
      <div className="space-y-2">
        <MonoLabel>capacity</MonoLabel>
        <div className="font-mono text-3xl text-[var(--fg)]">{data.capacity}</div>
        <GaugeBar value={Math.min(data.capacity, 2000)} max={2000} color="var(--accent-secondary)" />
      </div>
      <div className="space-y-2">
        <MonoLabel>flagged</MonoLabel>
        <div className="font-mono text-3xl text-[var(--fg)]">{totalFlagged}</div>
        <div className="flex gap-4 text-[11px] font-mono text-[var(--fg-muted)]">
          <span>stale {data.flagged.stale_working_count}</span>
          <span>low {data.flagged.low_value_count}</span>
          <span>conflict {data.flagged.contradiction_count}</span>
        </div>
      </div>
    </Card>
  );
}
```

- [ ] **Step 3: `ui/components/hygiene/pressure-explainer.tsx`**

```typescript
import type { PressureResponse } from "@/lib/schemas";

export function PressureExplainer({ data }: { data: PressureResponse }) {
  const score = data.load_score;
  const state = score < 0.2 ? "quiet" : score < 0.5 ? "active" : "saturated";
  const candidateCount =
    data.flagged.stale_working_count + data.flagged.low_value_count;
  return (
    <p className="text-sm text-[var(--fg-muted)]">
      This project is <span className="text-[var(--fg)]">{state}</span>.
      {" "}
      {candidateCount} {candidateCount === 1 ? "memory is a candidate" : "memories are candidates"} for prune.
    </p>
  );
}
```

- [ ] **Step 4: Run the test**

```bash
cd ui && npm test -- pressure-gauges 2>&1 | tail -15
```

- [ ] **Step 5: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/components/hygiene/pressure-gauges.tsx ui/components/hygiene/pressure-explainer.tsx ui/tests/pressure-gauges.test.tsx
git commit -m "feat(ui): PressureGauges + PressureExplainer with ARIA meters

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 22: PruneBuilder + PrunePlanReview

**Files:**
- Create: `ui/components/hygiene/prune-builder.tsx`
- Create: `ui/components/hygiene/prune-plan-review.tsx`

- [ ] **Step 1: `ui/components/hygiene/prune-builder.tsx`**

```typescript
"use client";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { SerifHeading } from "@/components/ui/serif-heading";
import { MonoLabel } from "@/components/ui/mono-label";

type Props = {
  onBuild: () => void;
  loading: boolean;
  disabled?: boolean;
};

export function PruneBuilder({ onBuild, loading, disabled }: Props) {
  return (
    <Card variant="flat" className="flex items-center justify-between gap-6">
      <div>
        <SerifHeading title="Build a prune plan" size="section" eyebrow="DRY RUN" />
        <p className="mt-1 text-sm text-[var(--fg-muted)]">
          Selects up to 200 candidates. Identity tier and memories with no salience are never selected.
        </p>
      </div>
      <div className="flex items-center gap-3">
        <MonoLabel>max 200</MonoLabel>
        <Button onClick={onBuild} loading={loading} disabled={disabled}>
          Build plan
        </Button>
      </div>
    </Card>
  );
}
```

- [ ] **Step 2: `ui/components/hygiene/prune-plan-review.tsx`**

```typescript
"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { MonoLabel } from "@/components/ui/mono-label";
import { Badge } from "@/components/ui/badge";
import { Empty } from "@/components/ui/empty";
import type { PrunePlan } from "@/lib/schemas";

type Props = {
  plan: PrunePlan;
  children: (ctx: { expired: boolean }) => React.ReactNode;
};

function formatMs(ms: number): string {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function PrunePlanReview({ plan, children }: Props) {
  const expiresAt = new Date(plan.expires_at).getTime();
  const [remaining, setRemaining] = useState<number>(expiresAt - Date.now());

  useEffect(() => {
    const id = setInterval(() => setRemaining(expiresAt - Date.now()), 1000);
    return () => clearInterval(id);
  }, [expiresAt]);

  const expired = remaining <= 0;

  return (
    <Card variant="flat" className="space-y-4">
      <header className="flex items-center justify-between gap-4">
        <div>
          <MonoLabel>plan id</MonoLabel>
          <div className="mt-1 select-all font-mono text-sm text-[var(--fg)]">{plan.plan_id}</div>
        </div>
        <div className="text-right">
          <MonoLabel>expires in</MonoLabel>
          <div
            className="mt-1 font-mono text-2xl"
            style={{ color: expired ? "var(--fg-dim)" : "var(--fg)" }}
          >
            {expired ? "expired" : formatMs(remaining)}
          </div>
        </div>
      </header>

      {plan.candidates.length === 0 ? (
        <Empty title="Nothing to prune. Pressure is low." />
      ) : (
        <div className="overflow-hidden rounded-md border border-[var(--border)]">
          <table className="w-full text-left text-sm">
            <thead className="bg-[var(--surface-0)]">
              <tr>
                <th className="px-3 py-2 font-mono text-[11px] uppercase tracking-[0.08em] text-[var(--fg-muted)]">memory id</th>
                <th className="px-3 py-2 font-mono text-[11px] uppercase tracking-[0.08em] text-[var(--fg-muted)]">tier</th>
                <th className="px-3 py-2 font-mono text-[11px] uppercase tracking-[0.08em] text-[var(--fg-muted)]">age</th>
                <th className="px-3 py-2 font-mono text-[11px] uppercase tracking-[0.08em] text-[var(--fg-muted)]">salience</th>
                <th className="px-3 py-2 font-mono text-[11px] uppercase tracking-[0.08em] text-[var(--fg-muted)]">reason</th>
              </tr>
            </thead>
            <tbody>
              {plan.candidates.map((c) => (
                <tr key={c.memory_id} className="border-t border-[var(--border)]">
                  <td className="px-3 py-2 font-mono text-xs text-[var(--fg)]">{c.memory_id}</td>
                  <td className="px-3 py-2"><Badge kind="tier" value={c.tier} /></td>
                  <td className="px-3 py-2 font-mono text-xs text-[var(--fg-muted)]">{c.age_days}d</td>
                  <td className="px-3 py-2 font-mono text-xs text-[var(--fg-muted)]">{c.salience.toFixed(2)}</td>
                  <td className="px-3 py-2 text-xs text-[var(--fg-muted)]">{c.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {children({ expired })}
    </Card>
  );
}
```

- [ ] **Step 3: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/components/hygiene/prune-builder.tsx ui/components/hygiene/prune-plan-review.tsx
git commit -m "feat(ui): PruneBuilder + PrunePlanReview with countdown timer

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 23: PruneApplyGate (typed plan id confirmation)

**Files:**
- Create: `ui/components/hygiene/prune-apply-gate.tsx`

- [ ] **Step 1: `ui/components/hygiene/prune-apply-gate.tsx`**

```typescript
"use client";

import { useState } from "react";
import { AlertTriangle, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MonoLabel } from "@/components/ui/mono-label";

type Props = {
  planId: string;
  candidateCount: number;
  expired: boolean;
  loading: boolean;
  onRequestApply: () => void;
};

export function PruneApplyGate({ planId, candidateCount, expired, loading, onRequestApply }: Props) {
  const [typed, setTyped] = useState("");
  const primed = typed === planId && !expired && candidateCount > 0;

  if (candidateCount === 0) return null;

  return (
    <div className="space-y-4 rounded-md border border-[var(--accent-danger)]/40 bg-[var(--accent-danger)]/10 p-4">
      <div className="flex items-start gap-3">
        <ShieldAlert size={18} className="mt-0.5 shrink-0 text-[var(--accent-danger)]" />
        <div>
          <p className="font-serif text-base text-[var(--fg)]">
            {candidateCount} {candidateCount === 1 ? "memory" : "memories"} will be permanently deleted.
          </p>
          <p className="mt-1 text-xs text-[var(--fg-muted)]">
            Type the full plan id below to confirm. This is deliberately paranoid — paste-only
            muscle memory is not allowed.
          </p>
        </div>
      </div>

      <label className="block">
        <MonoLabel>type the plan id to confirm</MonoLabel>
        <input
          type="text"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          placeholder={`${planId.slice(0, 4)}…`}
          spellCheck={false}
          autoComplete="off"
          disabled={expired || loading}
          className="mt-1 w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 font-mono text-sm text-[var(--fg)] placeholder:text-[var(--fg-dim)] focus:border-[var(--accent-danger)] focus:outline-none disabled:opacity-50"
          aria-describedby="prune-danger"
        />
      </label>

      {typed && !primed && !expired ? (
        <p className="flex items-center gap-1.5 text-xs text-[var(--accent-warning)]">
          <AlertTriangle size={12} />
          does not match plan id
        </p>
      ) : null}

      <div className="flex justify-end">
        <Button
          variant={primed ? "danger" : "ghost"}
          onClick={onRequestApply}
          disabled={!primed || loading}
          loading={loading}
        >
          {expired ? "Plan expired" : loading ? "Deleting" : `Apply · delete ${candidateCount}`}
        </Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/components/hygiene/prune-apply-gate.tsx
git commit -m "feat(ui): PruneApplyGate — typed plan id confirmation for C1 safety

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 24: PruneApplyDialog (final modal)

**Files:**
- Create: `ui/components/hygiene/prune-apply-dialog.tsx`

- [ ] **Step 1: `ui/components/hygiene/prune-apply-dialog.tsx`**

```typescript
"use client";

import { useEffect, useState } from "react";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { MonoLabel } from "@/components/ui/mono-label";
import type { PrunePlan } from "@/lib/schemas";

type Props = {
  open: boolean;
  plan: PrunePlan | null;
  onClose: () => void;
  onConfirm: () => void;
  loading: boolean;
};

function countByTier(plan: PrunePlan | null): Record<string, number> {
  if (!plan) return {};
  const out: Record<string, number> = {};
  for (const c of plan.candidates) {
    out[c.tier] = (out[c.tier] ?? 0) + 1;
  }
  return out;
}

export function PruneApplyDialog({ open, plan, onClose, onConfirm, loading }: Props) {
  const [focused, setFocused] = useState(false);

  useEffect(() => {
    if (open) setFocused(false);
  }, [open]);

  const count = plan?.candidates.length ?? 0;
  const byTier = countByTier(plan);

  return (
    <Dialog open={open} onClose={onClose} title={`Delete ${count} memories?`}>
      <div className="space-y-4">
        <p className="text-sm text-[var(--fg-muted)]">
          This cannot be undone. The backend will remove each memory from the store, graph, and YAML file.
        </p>
        <div className="rounded-md border border-[var(--border)] bg-[var(--surface-0)] p-3">
          <MonoLabel>by tier</MonoLabel>
          <div className="mt-1.5 flex flex-wrap gap-3 font-mono text-xs text-[var(--fg)]">
            {Object.entries(byTier).map(([tier, n]) => (
              <span key={tier}>
                {tier}: {n}
              </span>
            ))}
          </div>
        </div>
        <div className="flex justify-end gap-3">
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={loading}
            ref={(el) => {
              if (el && !focused) {
                el.focus();
                setFocused(true);
              }
            }}
          >
            Cancel
          </Button>
          <Button variant="danger" onClick={onConfirm} loading={loading}>
            Delete {count} {count === 1 ? "memory" : "memories"}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/components/hygiene/prune-apply-dialog.tsx
git commit -m "feat(ui): PruneApplyDialog — final confirmation modal with tier breakdown

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 25: BackfillRunner

**Files:**
- Create: `ui/components/hygiene/backfill-runner.tsx`

- [ ] **Step 1: `ui/components/hygiene/backfill-runner.tsx`**

```typescript
"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { SerifHeading } from "@/components/ui/serif-heading";
import { MonoLabel } from "@/components/ui/mono-label";
import { useBackfillMutation } from "@/lib/queries/use-backfill";
import type { BackfillReport } from "@/lib/schemas";

export function BackfillRunner({ project }: { project?: string }) {
  const [lastReport, setLastReport] = useState<BackfillReport | null>(null);
  const [dryRunSucceeded, setDryRunSucceeded] = useState(false);
  const backfill = useBackfillMutation();

  const run = (dryRun: boolean) => {
    backfill.mutate(
      { dry_run: dryRun, project },
      {
        onSuccess: (report) => {
          setLastReport(report);
          if (dryRun) setDryRunSucceeded(true);
          toast.success(
            `${dryRun ? "Dry run" : "Backfill"} — total ${report.total}: ` +
              Object.entries(report.updated_by_tier)
                .map(([k, v]) => `${k}=${v}`)
                .join(", ")
          );
        },
        onError: (err) => toast.error(err.message),
      }
    );
  };

  return (
    <Card variant="flat" className="space-y-4">
      <SerifHeading title="Lifecycle backfill" size="section" eyebrow="ONE-SHOT MIGRATION" />
      <p className="text-sm text-[var(--fg-muted)]">
        Compute tier / durability / retention_days for every existing memory. Safe. Idempotent.
      </p>

      <div className="flex gap-3">
        <Button variant="ghost" onClick={() => run(true)} loading={backfill.isPending}>
          Dry run
        </Button>
        <Button variant="ghost" onClick={() => run(false)} disabled={!dryRunSucceeded || backfill.isPending}>
          Apply
        </Button>
      </div>

      {lastReport ? (
        <div className="rounded-md border border-[var(--border)] bg-[var(--surface-0)] p-3">
          <MonoLabel>last report · {lastReport.dry_run ? "dry" : "applied"}</MonoLabel>
          <div className="mt-1 font-mono text-xs text-[var(--fg)]">
            {JSON.stringify(lastReport.updated_by_tier)}
          </div>
        </div>
      ) : null}
    </Card>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/components/hygiene/backfill-runner.tsx
git commit -m "feat(ui): BackfillRunner — admin card for lifecycle backfill with dry run gate

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 26: /hygiene/page.tsx wiring

**Files:**
- Rewrite: `ui/app/hygiene/page.tsx`

- [ ] **Step 1: Replace the stub**

```typescript
"use client";

import { useState } from "react";
import { toast } from "sonner";
import { SerifHeading } from "@/components/ui/serif-heading";
import { Empty } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { PressureGauges } from "@/components/hygiene/pressure-gauges";
import { PressureExplainer } from "@/components/hygiene/pressure-explainer";
import { PruneBuilder } from "@/components/hygiene/prune-builder";
import { PrunePlanReview } from "@/components/hygiene/prune-plan-review";
import { PruneApplyGate } from "@/components/hygiene/prune-apply-gate";
import { PruneApplyDialog } from "@/components/hygiene/prune-apply-dialog";
import { BackfillRunner } from "@/components/hygiene/backfill-runner";
import { usePressure } from "@/lib/queries/use-pressure";
import { usePrunePlanMutation, usePruneApplyMutation } from "@/lib/queries/use-prune";
import { useProjectStore } from "@/lib/project-store";
import type { PrunePlan } from "@/lib/schemas";

export default function HygienePage() {
  const project = useProjectStore((s) => s.project);
  const pressure = usePressure(project);
  const planMutation = usePrunePlanMutation();
  const applyMutation = usePruneApplyMutation();

  const [plan, setPlan] = useState<PrunePlan | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const handleBuild = () => {
    planMutation.mutate(
      { project },
      {
        onSuccess: (result) => {
          setPlan(result);
          toast(
            result.candidates.length === 0
              ? "Nothing to prune."
              : `Plan ${result.plan_id.slice(0, 8)}… built. ${result.candidates.length} candidates.`
          );
        },
        onError: (err) => toast.error(err.message),
      }
    );
  };

  const handleApply = () => {
    if (!plan) return;
    applyMutation.mutate(
      { planId: plan.plan_id, confirm: plan.plan_id },
      {
        onSuccess: (res) => {
          setDialogOpen(false);
          setPlan(null);
          toast.success(`Deleted ${res.deleted.length}. Skipped ${res.skipped.length}.`);
        },
        onError: (err) => toast.error(err.message),
      }
    );
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <SerifHeading eyebrow="PRESSURE · PRUNE · BACKFILL" title={`Memory Hygiene · ${project}`} />

      <section className="space-y-3">
        {pressure.isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : pressure.data ? (
          <>
            <PressureGauges data={pressure.data} />
            <PressureExplainer data={pressure.data} />
          </>
        ) : (
          <Empty title="Could not load pressure" />
        )}
      </section>

      <section className="space-y-4">
        {plan === null ? (
          <PruneBuilder onBuild={handleBuild} loading={planMutation.isPending} />
        ) : (
          <PrunePlanReview plan={plan}>
            {({ expired }) => (
              <PruneApplyGate
                planId={plan.plan_id}
                candidateCount={plan.candidates.length}
                expired={expired}
                loading={applyMutation.isPending}
                onRequestApply={() => setDialogOpen(true)}
              />
            )}
          </PrunePlanReview>
        )}
      </section>

      <BackfillRunner project={project} />

      <PruneApplyDialog
        open={dialogOpen}
        plan={plan}
        loading={applyMutation.isPending}
        onClose={() => setDialogOpen(false)}
        onConfirm={handleApply}
      />
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/app/hygiene/page.tsx
git commit -m "feat(ui): wire Hygiene surface — pressure, prune flow, backfill

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 27: Keystone test — full prune flow

**Files:**
- Create: `ui/tests/prune-flow.test.tsx`

- [ ] **Step 1: Create the keystone test**

```typescript
import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import HygienePage from "@/app/hygiene/page";
import prunePlanFixture from "./fixtures/prune-plan.json";
import pressureFixture from "./fixtures/pressure.json";

vi.mock("@/lib/api/pressure", () => ({
  getPressure: vi.fn().mockResolvedValue(pressureFixture),
}));

const postPrunePlan = vi.fn().mockResolvedValue(prunePlanFixture);
const postPruneApply = vi.fn().mockResolvedValue({
  plan_id: prunePlanFixture.plan_id,
  deleted: ["w1", "w2"],
  skipped: [],
});

vi.mock("@/lib/api/prune", () => ({
  postPrunePlan: (...args: unknown[]) => postPrunePlan(...args),
  postPruneApply: (...args: unknown[]) => postPruneApply(...args),
}));

vi.mock("@/lib/api/backfill", () => ({
  postBackfill: vi.fn().mockResolvedValue({
    dry_run: true,
    project: null,
    updated_by_tier: {},
    skipped: [],
    errors: [],
    total: 0,
  }),
}));

function renderHygiene() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <HygienePage />
      <Toaster />
    </QueryClientProvider>
  );
}

describe("Prune flow (keystone)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test("build plan → type confirmation → dialog → apply → success toast", async () => {
    const user = userEvent.setup();
    renderHygiene();

    // Wait for pressure to load
    await waitFor(() => {
      expect(screen.getByText(/0\.12/)).toBeInTheDocument();
    });

    // Click "Build plan"
    await user.click(screen.getByRole("button", { name: /build plan/i }));

    // Wait for the plan review to appear
    await waitFor(() => {
      expect(screen.getByText(prunePlanFixture.plan_id)).toBeInTheDocument();
    });

    // Apply button exists but is ghost + disabled until typed id matches
    const applyInitial = screen.getByRole("button", { name: /apply/i });
    expect(applyInitial).toBeDisabled();

    // Type wrong id — stays disabled
    const input = screen.getByPlaceholderText(/…/);
    await user.type(input, "wrong");
    expect(screen.getByRole("button", { name: /apply/i })).toBeDisabled();

    // Clear and type correct
    await user.clear(input);
    await user.type(input, prunePlanFixture.plan_id);

    const primedApply = screen.getByRole("button", { name: /apply/i });
    expect(primedApply).toBeEnabled();

    // Click primed apply → dialog opens
    await user.click(primedApply);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/Delete 2 memories/i)).toBeInTheDocument();

    // Confirm in the dialog
    await user.click(screen.getByRole("button", { name: /delete 2 memories/i }));

    // Toast fires and apply was called with matching confirm
    await waitFor(() => {
      expect(postPruneApply).toHaveBeenCalledWith(prunePlanFixture.plan_id, prunePlanFixture.plan_id);
    });
  });

  test("apply is never called when typed id does not match", async () => {
    const user = userEvent.setup();
    renderHygiene();

    await waitFor(() => expect(screen.getByText(/0\.12/)).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /build plan/i }));
    await waitFor(() => expect(screen.getByText(prunePlanFixture.plan_id)).toBeInTheDocument());

    const input = screen.getByPlaceholderText(/…/);
    await user.type(input, "wrong");
    const apply = screen.getByRole("button", { name: /apply/i });
    expect(apply).toBeDisabled();

    // No dialog, no apply call
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(postPruneApply).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run the test**

```bash
cd ui && npm test -- prune-flow 2>&1 | tail -25
```

Expected: 2/2 pass. If the mock for `Providers` conflicts with the raw `QueryClientProvider` in the test, simplify by not relying on the root `Providers` — the test renders its own QueryClientProvider around the page.

If the page imports from `@/lib/project-store` (Zustand) and the test doesn't provide it, that's fine — the store has a default of `"general"`.

- [ ] **Step 3: Commit**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/tests/prune-flow.test.tsx
git commit -m "test(ui): keystone prune flow — build → type → dialog → apply → toast

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 28: Final gate — build, lint, all tests, P1-UI tag

- [ ] **Step 1: Run the full test suite**

```bash
cd ui && npm test 2>&1 | tail -15
```

Expected: all green. Target breakdown:
- `schemas.test.ts` — 9 tests
- `brain-canvas.test.tsx` — 2 tests
- `node-drawer.test.tsx` — 2 tests
- `kb-columns.test.tsx` — 2 tests
- `continuity.test.tsx` — 3 tests
- `pressure-gauges.test.tsx` — 1 test
- `prune-flow.test.tsx` — 2 tests

Total: ~21 tests passing.

- [ ] **Step 2: Run the production build**

```bash
cd ui && npm run build 2>&1 | tail -25
```

Expected: `✓ Compiled successfully`, all four routes pre-rendered or marked as dynamic.

- [ ] **Step 3: Run the linter**

```bash
cd ui && npm run lint 2>&1 | tail -15
```

Expected: no errors. Warnings are acceptable if they come from third-party types.

- [ ] **Step 4: Smoke-test the dev server against the real backend**

```bash
cd /Users/demo-user/clawd/memento-mcp
# Ensure backend + qdrant running:
docker compose up -d qdrant
# Start backend in background:
(MCP_TRANSPORT=streamable-http HOST=0.0.0.0 PORT=8000 QDRANT_URL=http://localhost:6333 uv run python -m server &)
sleep 4

# Start UI in background
cd ui && (npm run dev &)
sleep 5

# Hit all four routes and confirm they return 200
curl -sfo /dev/null -w "%{http_code} /brain\n" http://localhost:3000/brain
curl -sfo /dev/null -w "%{http_code} /kb\n" http://localhost:3000/kb
curl -sfo /dev/null -w "%{http_code} /continuity\n" http://localhost:3000/continuity
curl -sfo /dev/null -w "%{http_code} /hygiene\n" http://localhost:3000/hygiene

# Clean up
pkill -f "next dev" 2>/dev/null
pkill -f "python -m server" 2>/dev/null
```

Expected: all four return `200`.

- [ ] **Step 5: Tag the gate**

```bash
cd /Users/demo-user/clawd/memento-mcp
git tag p1-ui-green
git log --oneline main..HEAD | head -40
```

- [ ] **Step 6: Show the final branch state**

```bash
git status
```

Expected: clean working tree. No staged changes. Working tree unchanged.

---

## Self-Review

**Spec coverage:**

| Spec section | Task(s) |
|---|---|
| Stack decisions (Next.js 15, TanStack Query, react-force-graph-2d, Tailwind v4, Zod) | 2 |
| Design tokens + palette + typography | 3 |
| QueryClient + project store + Sonner toaster | 4 |
| UI primitives (button, card, drawer, dialog, etc.) | 5 |
| CockpitShell + sidebar + header + project switcher + health badge | 6, 7 |
| Root layout + 4 routes | 8 |
| Zod schemas for all endpoints | 9 |
| Typed API clients | 10 |
| Query hooks with polling strategy | 11 |
| Contract tests against fixtures | 12 |
| BrainScene (aurora + starfield) | 13 |
| BrainCanvas (force-directed) | 14 |
| NodeDrawer + legends + stats | 15 |
| /brain page wiring | 16 |
| KB components (columns, slice, entry, empty) | 17 |
| /kb page wiring | 18 |
| Continuity components (resume, important, recent, next steps, conflicts, truncated) | 19 |
| /continuity page wiring | 20 |
| PressureGauges + explainer | 21 |
| PruneBuilder + PrunePlanReview with countdown | 22 |
| PruneApplyGate with typed id confirmation | 23 |
| PruneApplyDialog | 24 |
| BackfillRunner | 25 |
| /hygiene page wiring | 26 |
| Keystone prune flow test | 27 |
| Final green gate | 28 |

**Placeholder scan:** Every step contains the full code or the exact shell command. No "TBD", "TODO", or "add appropriate error handling" phrases. Every test file has real test bodies. Every code change shows the full replacement block.

**Type consistency check:**
- `PrunePlan`, `PruneCandidate`, `PruneApplyResponse` — consistent across Tasks 9, 10, 11, 22, 23, 24, 27
- `useBrainGraph` / `useMemoryDetail` / `usePrunePlanMutation` / `usePruneApplyMutation` — consistent across Tasks 11, 16, 26, 27
- `BrainCanvas` props — `{ nodes, links, selectedId, onNodeClick }` — consistent across Tasks 14 and 16
- `NodeDrawer` props — `{ open, detail, isLoading, onClose }` — consistent across Tasks 15 and 16
- `PrunePlanReview` uses render-prop pattern `children: (ctx: { expired: boolean }) => ReactNode` — consistent between Tasks 22 and 26

**Scope check:** All tasks touch only `ui/`. Zero backend changes. Exactly matches the spec's "touches ui/ entirely" scope.

---

## Run commands

```bash
# Fast unit tests (inside ui/)
cd ui && npm test

# Watch mode during development
cd ui && npm run test:watch

# Production build
cd ui && npm run build

# Linter
cd ui && npm run lint

# Dev server (backend must be running separately on :8000)
cd ui && npm run dev

# Full local stack
docker compose up -d qdrant
(MCP_TRANSPORT=streamable-http HOST=0.0.0.0 PORT=8000 QDRANT_URL=http://localhost:6333 uv run python -m server &)
cd ui && npm run dev
# Browse http://localhost:3000
```
