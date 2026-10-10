"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { WikiSidebar } from "@/components/wiki/wiki-sidebar";
import { WikiPageView } from "@/components/wiki/wiki-page";
import { WikiSearch } from "@/components/wiki/wiki-search";
import { WikiDraftView } from "@/components/wiki/wiki-draft-view";
import { WikiDraftsList } from "@/components/wiki/wiki-drafts";
import { WikiCandidates } from "@/components/wiki/wiki-candidates";
import { MemoryInspector } from "@/components/memory-inspector/memory-inspector";
import { SerifHeading } from "@/components/ui/serif-heading";
import { Empty } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { apiErrorMessage } from "@/lib/api/client";
import {
  useApproveDraft,
  useEditDraft,
  useRejectDraft,
  useWikiDraft,
  useWikiDrafts,
  useWikiIndex,
  useWikiPage,
} from "@/lib/queries/use-wiki";
import { useMemoryDetail } from "@/lib/queries/use-memory-detail";
import { useProjectStore } from "@/lib/project-store";
import { scopedTitle } from "@/lib/scoped-title";

type Tab = "search" | "drafts" | "candidates";

export default function WikiPage() {
  const project = useProjectStore((s) => s.project);
  const index = useWikiIndex(project);
  const drafts = useWikiDrafts();
  const approve = useApproveDraft();
  const reject = useRejectDraft();
  const edit = useEditDraft();
  const [tab, setTab] = useState<Tab>("search");
  const [selected, setSelected] = useState<string | null>(null);
  const [section, setSection] = useState<string | undefined>();
  const [full, setFull] = useState(false);
  const [draftId, setDraftId] = useState<string | null>(null);
  const [inspecting, setInspecting] = useState<string | null>(null);
  const page = useWikiPage(selected, section, full);
  const draft = useWikiDraft(draftId);
  const memoryDetail = useMemoryDetail(inspecting);

  useEffect(() => {
    setSelected(null);
    setSection(undefined);
    setFull(false);
    setDraftId(null);
  }, [project]);

  const open = (pageId: string, sectionId?: string | null) => {
    setDraftId(null);
    setSelected(pageId);
    setSection(sectionId ?? undefined);
    setFull(false);
  };
  const openDraft = (pageId: string) => {
    setSelected(null);
    setDraftId(pageId);
  };
  const doApprove = (id: string) =>
    approve.mutate(id, {
      onSuccess: () => {
        toast.success("Approved");
        setDraftId(null);
        open(id);
      },
      onError,
    });
  const doReject = (id: string) => {
    const reason = window.prompt("Reason for rejecting this draft?");
    if (reason === null) return;
    reject.mutate(
      { pageId: id, reason },
      {
        onSuccess: () => {
          toast.success("Rejected");
          setDraftId(null);
        },
        onError,
      }
    );
  };
  const doSave = (v: Parameters<typeof edit.mutate>[0]) =>
    edit.mutateAsync(v).then(
      () => (toast.success("Draft saved"), true),
      (e: unknown) => (onError(e), false),
    );
  const onError = (e: unknown) => toast.error(apiErrorMessage(e));

  return (
    <div className="mx-auto flex h-[calc(100vh-3.5rem)] max-w-7xl flex-col gap-6 p-6">
      <SerifHeading eyebrow="DOCS · LIVE" title={scopedTitle("Wiki", project)} />
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[240px_minmax(0,1fr)_320px]">
        <aside className="min-h-0 overflow-y-auto">
          {index.isLoading ? (
            <Skeleton className="h-full w-full" />
          ) : index.isError || !index.data ? (
            <Empty title="Could not load wiki" hint="Check backend connection" />
          ) : index.data.entries.length === 0 ? (
            <Empty title="No wiki pages yet" hint="Draft one from the Candidates tab" />
          ) : (
            <WikiSidebar entries={index.data.entries} selected={selected} onSelect={(id) => open(id)} />
          )}
        </aside>

        <main className="min-h-0 overflow-y-auto">
          {draftId ? (
            draft.isLoading ? (
              <Skeleton className="h-64 w-full" />
            ) : draft.isError || !draft.data ? (
              <Empty title="Could not load draft" hint={draft.error ? apiErrorMessage(draft.error) : undefined} />
            ) : (
              <WikiDraftView
                draft={draft.data}
                onApprove={doApprove}
                onReject={doReject}
                onOpenSource={setInspecting}
                onSave={doSave}
                saving={edit.isPending}
              />
            )
          ) : !selected ? (
            <Empty title="Select a page" />
          ) : page.isLoading ? (
            <Skeleton className="h-64 w-full" />
          ) : page.isError || !page.data ? (
            <Empty title="Could not load page" hint={page.error ? apiErrorMessage(page.error) : undefined} />
          ) : (
            <WikiPageView
              page={page.data}
              onOpenSource={setInspecting}
              onOpenSection={(sec) => {
                setFull(false);
                setSection(sec);
              }}
              full={full}
              onToggleFull={() => setFull((f) => !f)}
            />
          )}
        </main>

        <aside className="flex min-h-0 flex-col gap-3 overflow-y-auto">
          <div className="flex gap-1.5">
            {(
              [
                ["search", "Search"],
                ["drafts", `Drafts${drafts.data ? ` (${drafts.data.drafts.length})` : ""}`],
                ["candidates", "Candidates"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                aria-pressed={tab === key}
                onClick={() => setTab(key)}
                className={`cursor-pointer rounded-[7px] px-3 py-1.5 text-xs font-medium transition-colors duration-[150ms] ${
                  tab === key
                    ? "bg-[rgba(45,212,160,0.14)] text-[var(--fg)]"
                    : "border border-[var(--border)] text-[var(--fg-dim)] hover:text-[var(--fg)]"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          {tab === "search" ? (
            <WikiSearch project={project} onOpen={open} />
          ) : tab === "drafts" ? (
            <WikiDraftsList
              drafts={drafts.data?.drafts ?? []}
              onApprove={doApprove}
              onReject={doReject}
              onOpen={openDraft}
            />
          ) : (
            <WikiCandidates project={project} />
          )}
        </aside>
      </div>

      <MemoryInspector
        open={inspecting !== null}
        detail={memoryDetail.data}
        isLoading={memoryDetail.isLoading}
        currentProject={project}
        onClose={() => setInspecting(null)}
        onSelectMemory={setInspecting}
      />
    </div>
  );
}
