import { WikiPageView } from "./wiki-page";
import type { WikiDraftDetail } from "@/lib/schemas";

type Props = {
  draft: WikiDraftDetail;
  onApprove: (pageId: string) => void;
  onReject: (pageId: string) => void;
  onOpenSource?: (memoryId: string) => void;
};

const btn =
  "cursor-pointer rounded-[7px] border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--fg-dim)] hover:text-[var(--fg)] disabled:cursor-not-allowed disabled:opacity-40";

export function WikiDraftView({ draft, onApprove, onReject, onOpenSource }: Props) {
  const blocked = draft.has_redaction || draft.unsourced_steps > 0;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 rounded-[var(--radius-lg)] border border-[var(--border)] p-3">
        <button type="button" className={btn} disabled={blocked} onClick={() => onApprove(draft.page_id)}>
          Approve
        </button>
        <button type="button" className={btn} onClick={() => onReject(draft.page_id)}>
          Reject
        </button>
        {draft.needs.length ? <span className="text-xs text-amber-400">needs: {draft.needs.join(", ")}</span> : null}
        {draft.unsourced_steps > 0 ? (
          <span className="text-xs text-amber-400">unsourced steps: {draft.unsourced_steps}</span>
        ) : null}
        {draft.has_redaction ? <span className="text-xs text-red-400">contains redaction</span> : null}
      </div>
      <WikiPageView page={draft} onOpenSource={onOpenSource} />
    </div>
  );
}
