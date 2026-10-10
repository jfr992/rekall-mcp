import { MonoLabel } from "@/components/ui/mono-label";
import type { WikiDraft } from "@/lib/schemas";

type Props = {
  drafts: WikiDraft[];
  onApprove: (pageId: string) => void;
  onReject: (pageId: string) => void;
  onOpen: (pageId: string) => void;
};

const btn =
  "cursor-pointer rounded-[7px] border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--fg-dim)] hover:text-[var(--fg)] disabled:cursor-not-allowed disabled:opacity-40";

export function WikiDraftsList({ drafts, onApprove, onReject, onOpen }: Props) {
  if (!drafts.length) return <p className="text-sm text-[var(--fg-dim)]">No drafts pending.</p>;
  return (
    <ul className="space-y-3">
      {drafts.map((d) => {
        const blocked = d.has_redaction || d.unsourced_steps > 0;
        return (
          <li key={d.page_id} className="rounded-[var(--radius-lg)] border border-[var(--border)] p-3">
            <p className="text-sm text-[var(--fg)]">{d.title ?? d.page_id}</p>
            <MonoLabel className="block break-all">{d.page_id}</MonoLabel>
            {d.needs.length ? <p className="text-xs text-amber-400">needs: {d.needs.join(", ")}</p> : null}
            {d.unsourced_steps > 0 ? (
              <p className="text-xs text-amber-400">unsourced steps: {d.unsourced_steps}</p>
            ) : null}
            {d.has_redaction ? <p className="text-xs text-red-400">contains redaction</p> : null}
            <div className="mt-2 flex gap-2">
              <button type="button" className={btn} disabled={blocked} onClick={() => onApprove(d.page_id)}>
                Approve
              </button>
              <button type="button" className={btn} onClick={() => onReject(d.page_id)}>
                Reject
              </button>
              <button type="button" className={btn} onClick={() => onOpen(d.page_id)}>
                Open
              </button>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
