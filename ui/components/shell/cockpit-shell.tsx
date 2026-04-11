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
