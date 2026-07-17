"use client";

import { useEffect, useState } from "react";
import { Search } from "lucide-react";
import { Dialog } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { MonoLabel } from "@/components/ui/mono-label";
import { MemoryInspector } from "@/components/memory-inspector/memory-inspector";
import { useSearch } from "@/lib/queries/use-search";
import { useMemoryDetail } from "@/lib/queries/use-memory-detail";
import { useProjectStore } from "@/lib/project-store";

const DEBOUNCE_MS = 200;

export function GlobalSearch() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const project = useProjectStore((s) => s.project);
  const detail = useMemoryDetail(selectedId, project || undefined);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    const id = setTimeout(() => setQuery(input), DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [input]);

  const results = useSearch(open ? query : "", project);
  const memories = results.data?.memories ?? [];

  function close() {
    setOpen(false);
    setInput("");
    setQuery("");
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Search memories"
        className="flex shrink-0 cursor-pointer items-center gap-2 rounded-lg border border-[rgba(125,200,170,0.18)] px-3 py-1.5 text-[11px] text-[var(--fg-muted)] transition-colors hover:border-[rgba(45,212,160,0.5)] hover:text-[var(--fg-soft)]"
      >
        <Search size={12} />
        <span className="hidden md:inline">recall anything</span>
        <kbd className="hidden rounded border border-[var(--border)] px-1 font-mono text-[9px] font-medium text-[var(--fg-dim)] md:inline">
          ⌘K
        </kbd>
      </button>

      <Dialog open={open} onClose={close} title="Search memories">
        <input
          autoFocus
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Search memories…"
          className="w-full rounded-md border border-[var(--border)] bg-[var(--surface-0)] px-3 py-2 text-sm text-[var(--fg)] outline-none focus:border-[var(--border-strong)]"
        />

        {memories.length > 0 ? (
          <ul className="mt-3 max-h-[50vh] space-y-1 overflow-y-auto">
            {memories.map((m) => (
              <li key={m.memory_id}>
                <button
                  type="button"
                  onClick={() => {
                    setSelectedId(m.memory_id);
                    close();
                  }}
                  className="flex w-full items-center gap-3 rounded-md border border-transparent px-3 py-2 text-left hover:border-[var(--border)] hover:bg-[var(--surface-1)]"
                >
                  {m.type ? <Badge kind="type" value={m.type} /> : null}
                  <span className="min-w-0 flex-1 truncate text-sm text-[var(--fg)]">
                    {m.content}
                  </span>
                  {typeof m.score === "number" ? (
                    <MonoLabel>{m.score.toFixed(2)}</MonoLabel>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
        ) : query.trim() && results.isFetched ? (
          <p className="mt-3 text-sm text-[var(--fg-muted)]">No matches.</p>
        ) : null}
      </Dialog>

      <MemoryInspector
        open={selectedId !== null}
        detail={detail.data}
        isLoading={detail.isLoading}
        currentProject={project}
        onClose={() => setSelectedId(null)}
        onSelectMemory={setSelectedId}
      />
    </>
  );
}
