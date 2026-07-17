"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ProjectSwitcher } from "./project-switcher";
import { HealthBadge } from "./health-badge";
import { GlobalSearch } from "./global-search";
import { useInsights } from "@/lib/queries/use-insights";
import { useProjectStore } from "@/lib/project-store";

const tabs = [
  { href: "/brain", label: "Cockpit", tag: "COCKPIT" },
  { href: "/kb", label: "Knowledge Base", tag: "KNOWLEDGE BASE" },
  { href: "/stream", label: "Stream", tag: "STREAM" },
  { href: "/sessions", label: "Sessions", tag: "SESSIONS" },
  { href: "/hygiene", label: "Hygiene", tag: "HYGIENE" },
  { href: "/continuity", label: "Continuity", tag: "CONTINUITY" },
] as const;

function ScopeCounts() {
  const project = useProjectStore((s) => s.project);
  const { data } = useInsights(project);
  if (!data) return null;
  return (
    <span className="hidden shrink-0 font-mono text-[10px] text-[var(--fg-dim)] lg:inline">
      {data.in_scope} in scope · {data.total} total
    </span>
  );
}

export function CockpitShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "";
  const viewTag = tabs.find((t) => pathname.startsWith(t.href))?.tag ?? "COCKPIT";

  return (
    <div className="flex min-h-screen min-w-0 flex-col bg-[var(--bg-deep)]">
      <header
        className="sticky top-0 flex items-center gap-3 border-b border-[var(--border)] bg-[var(--bg-frost)] px-4 py-2.5 backdrop-blur-[8px] md:gap-4 md:px-6"
        style={{ zIndex: "var(--z-shell)" }}
      >
        <div className="flex shrink-0 items-baseline gap-2">
          <span className="font-serif text-xl font-medium italic text-[var(--fg)]">Rekall</span>
          <span className="hidden font-mono text-[9px] font-medium tracking-[0.18em] text-[var(--fg-faint)] sm:inline">
            {viewTag}
          </span>
        </div>

        <nav
          aria-label="Primary"
          className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto whitespace-nowrap [scrollbar-width:none]"
        >
          {tabs.map((tab) => {
            const active = pathname.startsWith(tab.href);
            return (
              <Link
                key={tab.href}
                href={tab.href}
                className={`shrink-0 rounded-[7px] px-3 py-1.5 text-xs font-medium transition-colors duration-[150ms] ${
                  active
                    ? "bg-[rgba(45,212,160,0.14)] text-[var(--fg)]"
                    : "text-[var(--fg-dim)] hover:text-[var(--fg)]"
                }`}
              >
                {tab.label}
              </Link>
            );
          })}
        </nav>

        <ProjectSwitcher />
        <GlobalSearch />
        <HealthBadge />
        <ScopeCounts />
      </header>

      <main className="min-w-0 flex-1 overflow-auto">{children}</main>
    </div>
  );
}
