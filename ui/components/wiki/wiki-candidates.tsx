import { useState } from "react";
import { toast } from "sonner";
import { MonoLabel } from "@/components/ui/mono-label";
import { apiErrorMessage } from "@/lib/api/client";
import { useClassifyCandidates, useCreateDraft, useWikiCandidates } from "@/lib/queries/use-wiki";

const btn =
  "cursor-pointer rounded-[7px] border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--fg-dim)] hover:text-[var(--fg)] disabled:cursor-not-allowed disabled:opacity-40";

export function WikiCandidates({ project }: { project: string }) {
  const { data, error } = useWikiCandidates(project);
  const { mutate: classify, isPending, error: startError } = useClassifyCandidates();
  const create = useCreateDraft();
  const [picked, setPicked] = useState<Set<string>>(new Set());

  const candidates = data?.candidates ?? [];
  const running = isPending || data?.status === "running";
  const toggle = (id: string) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  const chosen = candidates.filter((c) => picked.has(c.memory_id));
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
      <ul className="space-y-2">
        {candidates.map((c) => (
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
                <span className="block text-sm text-[var(--fg)]">{c.question ?? c.content.slice(0, 80)}</span>
                <MonoLabel className="block">{c.page_type}</MonoLabel>
                {c.reasons.length ? (
                  <span className="block text-xs text-[var(--fg-dim)]">{c.reasons.join("; ")}</span>
                ) : null}
              </span>
            </label>
          </li>
        ))}
      </ul>
      {candidates.length ? (
        <button type="button" className={btn} disabled={!chosen.length || mixedTypes || create.isPending} onClick={draftSelected}>
          Draft selected
        </button>
      ) : null}
      {mixedTypes ? (
        <p className="text-xs text-amber-400">Select candidates of the same page type to draft them together.</p>
      ) : null}
    </div>
  );
}
