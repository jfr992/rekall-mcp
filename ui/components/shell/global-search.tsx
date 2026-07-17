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

type SearchMode = "semantic" | "exact";

const MODES: SearchMode[] = ["semantic", "exact"];

export function GlobalSearch() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("semantic");
  const [activeIndex, setActiveIndex] = useState(0);
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

  const results = useSearch(open ? query : "", project, mode);
  const fetched = results.data?.memories ?? [];
  const needle = query.trim().toLowerCase();
  const memories =
    mode === "exact"
      ? fetched.filter((m) => (m.content ?? "").toLowerCase().includes(needle))
      : fetched;

  // Highlight resets whenever the visible result set changes.
  useEffect(() => {
    setActiveIndex(0);
  }, [query, mode]);

  function close() {
    setOpen(false);
    setInput("");
    setQuery("");
    setActiveIndex(0);
  }

  function openMemory(memoryId: string) {
    setSelectedId(memoryId);
    close();
  }

  function onInputKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, memories.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      const m = memories[activeIndex];
      if (m) openMemory(m.memory_id);
    }
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

      <Dialog open={open} onClose={close} title="Search memories" titleHidden>
        <div className="flex items-center gap-3 border-b border-[var(--border)] pb-3">
          <span className="shrink-0 font-mono text-[11px] font-medium tracking-[0.1em] text-[var(--accent-primary)]">
            RECALL
          </span>
          <input
            autoFocus
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Search memories…"
            onKeyDown={onInputKey}
            className="min-w-0 flex-1 border-none bg-transparent text-base text-[var(--fg)] outline-none placeholder:text-[var(--fg-dim)]"
          />
          <span className="flex shrink-0 items-center gap-1.5">
            {MODES.map((m) => (
              <button
                key={m}
                type="button"
                aria-pressed={mode === m}
                onClick={() => setMode(m)}
                className={`cursor-pointer rounded-full border px-2.5 py-0.5 font-mono text-[10px] font-medium transition-colors ${
                  mode === m
                    ? "border-[rgba(45,212,160,0.4)] bg-[rgba(45,212,160,0.16)] text-[var(--accent-bright)]"
                    : "border-[var(--border)] text-[var(--fg-muted)] hover:text-[var(--fg-soft)]"
                }`}
              >
                {m}
              </button>
            ))}
          </span>
        </div>

        {memories.length > 0 ? (
          <ul className="mt-3 max-h-[50vh] space-y-1 overflow-y-auto">
            {memories.map((m, i) => (
              <li key={m.memory_id}>
                <button
                  type="button"
                  onClick={() => openMemory(m.memory_id)}
                  onMouseEnter={() => setActiveIndex(i)}
                  className={`flex w-full items-center gap-3 rounded-md border px-3 py-2 text-left ${
                    i === activeIndex
                      ? "border-[var(--border)] bg-[var(--surface-1)]"
                      : "border-transparent"
                  }`}
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
          <p className="mt-3 py-4 text-center text-sm text-[var(--fg-muted)]">
            {mode === "exact" ? "No exact matches in top 50." : "No matches."}
          </p>
        ) : null}

        <p className="mt-3 border-t border-[var(--border)] pt-2.5 font-mono text-[10px] text-[var(--fg-dim)]">
          ↑↓ navigate · ↵ open · esc close
        </p>
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
