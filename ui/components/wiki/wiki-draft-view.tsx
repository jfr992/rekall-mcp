import { useState } from "react";
import { WikiPageView } from "./wiki-page";
import type { WikiDraftDetail } from "@/lib/schemas";

type Props = {
  draft: WikiDraftDetail;
  onApprove: (pageId: string) => void;
  onReject: (pageId: string) => void;
  onOpenSource?: (memoryId: string) => void;
  onSave?: (edit: { pageId: string; body: string; title: string; description: string }) => Promise<boolean>;
  saving?: boolean;
};

const btn =
  "cursor-pointer rounded-[7px] border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--fg-dim)] hover:text-[var(--fg)] disabled:cursor-not-allowed disabled:opacity-40";

const field =
  "w-full rounded-[7px] border border-[var(--border)] bg-transparent p-2 text-sm text-[var(--fg)]";

export function WikiDraftView({ draft, onApprove, onReject, onOpenSource, onSave, saving }: Props) {
  const [editing, setEditing] = useState(false);
  const [body, setBody] = useState(draft.body);
  const [title, setTitle] = useState(draft.title ?? "");
  const [description, setDescription] = useState(draft.description ?? "");
  const startEdit = () => {
    setBody(draft.body);
    setTitle(draft.title ?? "");
    setDescription(draft.description ?? "");
    setEditing(true);
  };
  const save = async () => {
    if (await onSave?.({ pageId: draft.page_id, body, title, description })) setEditing(false);
  };
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
        {onSave && !editing ? (
          <button type="button" className={btn} onClick={startEdit}>
            Edit
          </button>
        ) : null}
        {draft.needs.length ? <span className="text-xs text-amber-400">needs: {draft.needs.join(", ")}</span> : null}
        {draft.unsourced_steps > 0 ? (
          <span className="text-xs text-amber-400">unsourced steps: {draft.unsourced_steps}</span>
        ) : null}
        {draft.has_redaction ? <span className="text-xs text-red-400">contains redaction</span> : null}
      </div>
      {editing ? (
        <div className="flex flex-col gap-2 rounded-[var(--radius-lg)] border border-[var(--border)] p-3">
          <label className="text-xs text-[var(--fg-dim)]" htmlFor="draft-title">
            Title
          </label>
          <input id="draft-title" className={field} value={title} onChange={(e) => setTitle(e.target.value)} />
          <label className="text-xs text-[var(--fg-dim)]" htmlFor="draft-description">
            Description
          </label>
          <input
            id="draft-description"
            className={field}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          <label className="text-xs text-[var(--fg-dim)]" htmlFor="draft-body">
            Body
          </label>
          <textarea
            id="draft-body"
            className={`${field} min-h-64 font-mono`}
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
          <div className="flex gap-2">
            <button type="button" className={btn} disabled={saving} onClick={save}>
              Save
            </button>
            <button type="button" className={btn} onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <WikiPageView page={draft} onOpenSource={onOpenSource} />
      )}
    </div>
  );
}
