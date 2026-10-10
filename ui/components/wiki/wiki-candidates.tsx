import { useMemo, useState } from "react";
import { toast } from "sonner";
import { MonoLabel } from "@/components/ui/mono-label";
import { apiErrorMessage } from "@/lib/api/client";
import { useClassifyCandidates, useCreateDraft, useWikiCandidates } from "@/lib/queries/use-wiki";

const btn =
  "cursor-pointer rounded-[7px] border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--fg-dim)] hover:text-[var(--fg)] disabled:cursor-not-allowed disabled:opacity-40";

const PAGE_TYPES = ["process", "policy", "reference", "entity"] as const;

export function WikiCandidates({
  project,
  onOpenSource,
}: {
  project: string;
  onOpenSource?: (memoryId: string) => void;
}) {
  const { data, error } = useWikiCandidates(project);
  const { mutate: classify, isPending, error: startError } = useClassifyCandidates();
  const create = useCreateDraft();
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [text, setText] = useState("");
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [hideUsed, setHideUsed] = useState(true);

  const candidates = data?.candidates ?? [];
  const textMatched = useMemo(() => {
    const q = text.trim().toLowerCase();
    return candidates.filter(
      (c) =>
        (!hideUsed || c.used_in.length === 0) &&
        (!q || [c.question ?? "", c.content, c.memory_id, ...c.reasons].some((f) => f.toLowerCase().includes(q)))
    );
  }, [candidates, text, hideUsed]);
  const visible = typeFilter ? textMatched.filter((c) => c.page_type === typeFilter) : textMatched;
  const countOf = (type: string) => textMatched.filter((c) => c.page_type === type).length;
  const clearFilters = () => {
    setText("");
    setTypeFilter(null);
    setHideUsed(false);
  };
  const selectAllVisible = () => setPicked((prev) => new Set([...prev, ...visible.map((c) => c.memory_id)]));
  const running = isPending || data?.status === "running";
  const toggle = (id: string) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  const chosen = visible.filter((c) => picked.has(c.memory_id));
  const hiddenPicks = picked.size - chosen.length;
  const usedHidden = hideUsed ? candidates.filter((c) => c.used_in.length).length : 0;
  const mixedTypes = new Set(chosen.map((c) => c.page_type)).size > 1;

  const draftSelected = () => {
    if (!chosen.length || mixedTypes) return;
    create.mutate(
      { memoryIds: chosen.map((c) => c.memory_id), pageType: chosen[0].page_type },
      {
        onSuccess: (res) => {
          setPicked(new Set());
          if (res.status !== "unconfigured") toast.success("Draft created - see the Drafts tab");
        },
      }
    );
  };

  return (
    <div className="flex flex-col gap-3">
      <button type="button" className={btn} disabled={running} onClick={() => classify(project)}>
        {running ? `Classifying ${data?.done ?? 0}/${data?.total ?? 0}…` : "Classify"}
      </button>
      {error || startError ? (
        <p className="text-sm text-red-400">{apiErrorMessage(error ?? startError)}</p>
      ) : null}
      {data?.status === "error" ? <p className="text-sm text-red-400">{data.error}</p> : null}
      {data?.status === "unconfigured" ? (
        <p className="text-sm text-[var(--fg-dim)]">Wiki model is not configured on the backend.</p>
      ) : null}
      {create.data && create.data.status === "unconfigured" ? (
        <p className="text-sm text-[var(--fg-dim)]">Wiki model is not configured on the backend.</p>
      ) : null}
      {create.error ? <p className="text-sm text-red-400">{apiErrorMessage(create.error)}</p> : null}
      {candidates.length ? (
        <div className="flex flex-col gap-2">
          <input
            type="search"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Filter candidates"
            aria-label="Filter candidates"
            className="rounded-[7px] border border-[var(--border)] bg-transparent px-2.5 py-1 text-xs text-[var(--fg)]"
          />
          <div className="flex flex-wrap gap-1.5">
            {[["all", null, textMatched.length] as const, ...PAGE_TYPES.map((t) => [t, t, countOf(t)] as const)].map(
              ([label, value, n]) => (
                <button
                  key={label}
                  type="button"
                  aria-pressed={typeFilter === value}
                  onClick={() => setTypeFilter(value)}
                  className={`${btn} ${typeFilter === value ? "bg-[rgba(45,212,160,0.14)] text-[var(--fg)]" : ""}`}
                >
                  {label} {n}
                </button>
              )
            )}
          </div>
          <div className="flex items-center justify-between gap-2">
            <label className="flex cursor-pointer items-center gap-1.5 text-xs text-[var(--fg-dim)]">
              <input type="checkbox" checked={hideUsed} onChange={() => setHideUsed((v) => !v)} />
              Hide used
            </label>
            {typeFilter ? (
              <button type="button" className={btn} onClick={selectAllVisible}>
                Select all visible
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
      {candidates.length && !visible.length ? (
        <div className="flex flex-col items-start gap-2">
          <p className="text-sm text-[var(--fg-dim)]">
            No candidates match{usedHidden ? ` (${usedHidden} hidden as already used)` : ""}
          </p>
          <button type="button" className={btn} onClick={clearFilters}>
            Clear filters
          </button>
        </div>
      ) : null}
      <ul className="space-y-2">
        {visible.map((c) => (
          <li key={c.memory_id} className="rounded-[var(--radius-lg)] border border-[var(--border)] p-3">
            <label className="flex cursor-pointer items-start gap-2">
              <input
                type="checkbox"
                checked={picked.has(c.memory_id)}
                onChange={() => toggle(c.memory_id)}
                aria-label={`Select ${c.memory_id}`}
                className="mt-1"
              />
              <span className="min-w-0">
                <MonoLabel className="block">
                  {[c.date, c.project, c.page_type].filter(Boolean).join(" · ")}
                </MonoLabel>
                <span className="block text-sm text-[var(--fg)]">{c.question ?? c.content.slice(0, 80)}</span>
                {c.used_in.length ? (
                  <span className="block text-xs text-amber-400">in {c.used_in.join(", ")}</span>
                ) : null}
              </span>
            </label>
            <div className="mt-1 flex items-start gap-3 pl-6 text-xs text-[var(--fg-dim)]">
              {c.reasons.length ? (
                <details>
                  <summary className="cursor-pointer">why</summary>
                  {c.reasons.join("; ")}
                </details>
              ) : null}
              {onOpenSource ? (
                <button type="button" className="cursor-pointer hover:text-[var(--fg)]" onClick={() => onOpenSource(c.memory_id)}>
                  show memory
                </button>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
      {picked.size ? (
        <div className="sticky bottom-0 flex flex-col gap-1 border-t border-[var(--border)] bg-[var(--bg-base)] py-2">
          {mixedTypes ? (
            <p className="text-xs text-amber-400">Select candidates of the same page type to draft them together.</p>
          ) : null}
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-[var(--fg-dim)]">{chosen.length} selected{hiddenPicks ? ` · +${hiddenPicks} hidden` : ""}</span>
            <span className="flex gap-2">
              <button type="button" className={btn} onClick={() => setPicked(new Set())}>
                Clear
              </button>
              <button type="button" className={btn} disabled={!chosen.length || mixedTypes || create.isPending} onClick={draftSelected}>
                Draft as {mixedTypes || !chosen.length ? "…" : chosen[0].page_type}
              </button>
            </span>
          </div>
        </div>
      ) : null}
    </div>
  );
}
