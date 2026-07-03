"use client";

import type { ReactNode } from "react";
import { SerifHeading } from "@/components/ui/serif-heading";
import { SidebarNav, MobileNav } from "./sidebar-nav";
import { ProjectSwitcher } from "./project-switcher";
import { HealthBadge } from "./health-badge";
import { HeaderBar } from "./header-bar";

export function CockpitShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-[var(--bg-deep)] md:flex-row">
      {/* Mobile-only top bar */}
      <header className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--bg-base)] px-4 py-3 md:hidden">
        <SerifHeading eyebrow="REKALL" title="Cockpit" size="section" />
        <MobileNav />
      </header>

      {/* Desktop sidebar — hidden on mobile, flex column from md up */}
      <aside
        className="hidden w-60 flex-col gap-6 border-r border-[var(--border)] bg-[var(--bg-base)] px-4 py-6 md:flex"
        style={{ zIndex: "var(--z-shell)" }}
      >
        <SerifHeading eyebrow="REKALL" title="Cockpit" size="section" />
        <ProjectSwitcher />
        <SidebarNav />
        <div className="mt-auto">
          <HealthBadge />
        </div>
      </aside>

      {/* Content area — min-w-0 prevents flex children from overflowing */}
      <div className="flex min-w-0 flex-1 flex-col">
        <HeaderBar />
        <main className="flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
