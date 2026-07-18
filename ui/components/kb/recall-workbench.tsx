"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Empty } from "@/components/ui/empty";
import { MonoLabel } from "@/components/ui/mono-label";
import { MemoryInspector } from "@/components/memory-inspector/memory-inspector";
import { useSearch } from "@/lib/queries/use-search";
import { useMemoryDetail } from "@/lib/queries/use-memory-detail";
import { tokens, typeColor } from "@/lib/theme";

const DEBOUNCE_MS = 200;
const RECALL_LIMIT = 30;

type Props = {
  project: string;
};

// Canonical type ordering for the facet rail — theme token order.
const TYPE_ORDER = Object.keys(tokens.type);

// Client-side date filter: Qdrant Range on the YYYY-MM-DD string is a known
// pitfall, so recency is a post-retrieval string compare.
const RECENCY_OPTIONS = ["all", "24h", "7d", "30d"] as const;
type Recency = (typeof RECENCY_OPTIONS)[number];
const RECENCY_DAYS: Record<Recency, number | null> = {
  all: null,
  "24h": 1,
  "7d": 7,
  "30d": 30,
};

function recencyCutoff(recency: Recency): string | null {
  const days = RECENCY_DAYS[recency];
  if (days === null) return null;
  return new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 10);
}

export function RecallWorkbench({ project }: Props) {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [recency, setRecency] = useState<Recency>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const detail = useMemoryDetail(selectedId, project || undefined);

  useEffect(() => {
    const id = setTimeout(() => setQuery(input), DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [input]);

  const results = useSearch(query, project, "semantic", RECALL_LIMIT);
  const fetched = results.data?.memories ?? [];

  const cutoff = recencyCutoff(recency);
  // Memories without a date can't honestly pass a recency filter — drop them.
  const memories = cutoff
    ? fetched.filter((m) => (m.date ?? "") >= cutoff)
    : fetched;

  const typeCounts = new Map<string, number>();
  for (const m of memories) {
    const t = m.type ?? "note";
    typeCounts.set(t, (typeCounts.get(t) ?? 0) + 1);
  }
  const facetTypes = [...typeCounts.keys()].sort(
    (a, b) => TYPE_ORDER.indexOf(a) - TYPE_ORDER.indexOf(b),
  );

  const shown = typeFilter
    ? memories.filter((m) => (m.type ?? "note") === typeFilter)
    : memories;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="mx-auto w-full max-w-3xl">
        <div className="flex items-center gap-3 rounded-[10px] border border-[rgba(45,212,160,0.35)] bg-[var(--surface-1)] px-4 py-3 shadow-[0_0_0_4px_rgba(45,212,160,0.06)]">
          <span className="shrink-0 font-mono text-[13px] font-medium text-[var(--accent-primary)]">
            recall ▸
          </span>
          <input
            autoFocus
            type="text"
            aria-label="Recall query"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="how does the user prefer error handling?"
            className="min-w-0 flex-1 border-none bg-transparent text-base text-[var(--fg)] outline-none placeholder:text-[var(--fg-dim)]"
          />
        </div>
        {results.data ? (
          <p className="mt-2 text-right font-mono text-[10px] text-[var(--fg-dim)]">
            {`${fetched.length} results · ${shown.length} shown`}
          </p>
        ) : null}
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[180px_1fr] gap-6">
        <aside className="flex flex-col gap-6 border-r border-[var(--border)] pr-4">
          <div role="group" aria-label="Type facets">
            <MonoLabel className="mb-2.5 block tracking-[0.16em]">TYPE</MonoLabel>
            <div className="flex flex-col gap-1.5">
              <button
                type="button"
                aria-pressed={typeFilter === null}
                onClick={() => setTypeFilter(null)}
                className={`flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-left text-xs transition-colors hover:text-[var(--fg)] ${
                  typeFilter === null ? "text-[var(--fg)]" : "text-[var(--fg-muted)]"
                }`}
              >
                <span
                  aria-hidden
                  className="h-[7px] w-[7px] rounded-full"
                  style={{ background: "var(--accent-primary)" }}
                />
                all
                <span className="ml-auto font-mono text-[10px] text-[var(--fg-dim)]">
                  {memories.length}
                </span>
              </button>
              {facetTypes.map((t) => (
                <button
                  key={t}
                  type="button"
                  aria-pressed={typeFilter === t}
                  onClick={() =>
                    setTypeFilter((cur) => (cur === t ? null : t))
                  }
                  className={`flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-left text-xs transition-colors hover:text-[var(--fg)] ${
                    typeFilter === t ? "text-[var(--fg)]" : "text-[var(--fg-muted)]"
                  }`}
                >
                  <span
                    aria-hidden
                    className="h-[7px] w-[7px] rounded-full"
                    style={{
                      background: typeColor(t),
                      boxShadow:
                        typeFilter === t
                          ? "0 0 0 2px rgba(45,212,160,0.3)"
                          : "none",
                    }}
                  />
                  {t}
                  <span className="ml-auto font-mono text-[10px] text-[var(--fg-dim)]">
                    {typeCounts.get(t)}
                  </span>
                </button>
              ))}
            </div>
          </div>

          <div role="group" aria-label="Recency">
            <MonoLabel className="mb-2.5 block tracking-[0.16em]">RECENCY</MonoLabel>
            <div className="flex flex-col gap-1.5">
              {RECENCY_OPTIONS.map((r) => (
                <button
                  key={r}
                  type="button"
                  aria-pressed={recency === r}
                  onClick={() => setRecency(r)}
                  className={`cursor-pointer rounded px-1 py-0.5 text-left text-xs transition-colors hover:text-[var(--fg)] ${
                    recency === r ? "text-[var(--fg)]" : "text-[var(--fg-muted)]"
                  }`}
                >
                  {r}
                </button>
              ))}
            </div>
          </div>
        </aside>

        {!query.trim() ? (
          <Empty
            title="Type to recall"
            hint={`Semantic search over ${project || "all"} memories — top ${RECALL_LIMIT} by score`}
          />
        ) : shown.length > 0 ? (
        <ul
          aria-label="Recall results"
          className="flex min-h-0 flex-col gap-2.5 overflow-y-auto pb-4"
        >
          {shown.map((m) => (
            <li key={m.memory_id}>
              <button
                type="button"
                onClick={() => {
                  setSelectedId(m.memory_id);
                  setInspectorOpen(true);
                }}
                className={`w-full cursor-pointer rounded-[9px] border px-4 py-3.5 text-left transition-colors hover:border-[rgba(45,212,160,0.5)] ${
                  selectedId === m.memory_id
                    ? "border-[rgba(45,212,160,0.45)] bg-[var(--surface-1)]"
                    : "border-[var(--border)] bg-[var(--bg-elevated)]"
                }`}
              >
                <div className="mb-2 flex items-center gap-2.5">
                  {typeof m.score === "number" ? (
                    <span className="font-mono text-xs font-semibold text-[var(--fg-muted)]">
                      {m.score.toFixed(2)}
                    </span>
                  ) : null}
                  {m.type ? <Badge kind="type" value={m.type} /> : null}
                  <MonoLabel className="ml-auto">{m.date ?? "—"}</MonoLabel>
                </div>
                <p className="line-clamp-3 text-sm leading-relaxed text-[var(--fg-soft)]">
                  {m.content}
                </p>
                {selectedId === m.memory_id &&
                (detail.data?.relationships?.length ?? 0) > 0 ? (
                  <div className="mt-3 flex flex-col gap-1.5">
                    <MonoLabel className="tracking-[0.16em]">
                      LINKED MEMORIES
                    </MonoLabel>
                    {detail.data!.relationships!.map((rel) => (
                      <span
                        key={`${rel.neighbor_id}-${rel.relation}-${rel.direction}`}
                        className="flex items-center gap-2 rounded-[7px] border border-[var(--border)] bg-[var(--surface-1)] px-2.5 py-1.5 text-xs text-[var(--fg-soft)]"
                      >
                        <span
                          aria-hidden
                          className="h-1.5 w-1.5 shrink-0 rounded-full"
                          style={{ background: typeColor(rel.memory?.type) }}
                        />
                        <span className="min-w-0 flex-1 truncate">
                          {rel.memory?.content ?? rel.neighbor_id}
                        </span>
                        {typeof rel.weight === "number" ? (
                          <span className="shrink-0 font-mono text-[9px] text-[var(--fg-dim)]">
                            {rel.weight.toFixed(2)}
                          </span>
                        ) : null}
                      </span>
                    ))}
                  </div>
                ) : null}
              </button>
            </li>
          ))}
        </ul>
        ) : results.isFetched ? (
          <Empty
            title={fetched.length > 0 ? "Nothing in this slice" : "No matches"}
            hint={
              fetched.length > 0
                ? "Results exist but the active type/recency filters hide them all"
                : `Nothing matches “${query}” in ${project || "all projects"}`
            }
          />
        ) : (
          <div />
        )}
      </div>

      <MemoryInspector
        open={inspectorOpen}
        detail={detail.data}
        isLoading={detail.isLoading}
        currentProject={project}
        onClose={() => setInspectorOpen(false)}
        onSelectMemory={setSelectedId}
      />
    </div>
  );
}
