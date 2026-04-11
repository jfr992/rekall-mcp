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
