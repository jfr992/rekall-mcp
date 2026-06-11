"use client";

import { ChevronsUpDown, User } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useProjectStore } from "@/lib/project-store";
import { useProjects } from "@/lib/queries/use-projects";

export function ProjectSwitcher() {
  const project = useProjectStore((s) => s.project);
  const setProject = useProjectStore((s) => s.setProject);
  const { data, isLoading, isError } = useProjects();
  const qc = useQueryClient();

  const projects = data?.projects ?? [];
  const total = data?.total ?? 0;

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setProject(e.target.value);
    // Only project-scoped data depends on scope; leave the project list and
    // health badge alone so the switcher and header don't flicker on change.
    qc.invalidateQueries({
      predicate: (q) => {
        const key = q.queryKey[0];
        return key !== "projects" && key !== "health";
      },
    });
  };

  return (
    <label className="flex flex-col gap-1.5 rounded-md border border-[var(--border)] bg-[var(--surface-0)] px-3 py-2">
      <span className="flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.08em] text-[var(--fg-muted)]">
        <User size={12} />
        scope
      </span>
      <div className="relative">
        <select
          value={project}
          onChange={handleChange}
          aria-label="Memory scope"
          className="w-full cursor-pointer appearance-none bg-transparent pr-6 text-sm text-[var(--fg)] focus:outline-none disabled:cursor-wait disabled:opacity-50"
          disabled={isLoading}
        >
          {isLoading ? (
            <option value="">loading…</option>
          ) : isError ? (
            <option value="">error</option>
          ) : (
            <>
              <option value="" className="bg-[var(--bg-base)] text-[var(--fg)]">
                all memories · {total}
              </option>
              {projects.map((p) => (
                <option key={p.name} value={p.name} className="bg-[var(--bg-base)] text-[var(--fg)]">
                  {p.name} · {p.count}
                </option>
              ))}
            </>
          )}
        </select>
        <ChevronsUpDown
          size={12}
          className="pointer-events-none absolute right-0 top-1/2 -translate-y-1/2 text-[var(--fg-dim)]"
        />
      </div>
    </label>
  );
}
