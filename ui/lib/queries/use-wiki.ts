import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  approveDraft,
  createDraft,
  editDraft,
  getWikiCandidates,
  getWikiDraft,
  getWikiDrafts,
  getWikiIndex,
  getWikiPage,
  rejectDraft,
  searchWiki,
  startClassify,
  type DraftEdit,
} from "@/lib/api/wiki";

export function useWikiIndex(project: string) {
  return useQuery({
    queryKey: ["wiki", "index", project],
    queryFn: () => getWikiIndex(project),
    staleTime: 60_000,
  });
}

export function useWikiSearch(q: string, project: string) {
  return useQuery({
    queryKey: ["wiki", "search", q, project],
    queryFn: () => searchWiki(q, project),
    enabled: q.length > 1,
  });
}

export function useWikiPage(pageId: string | null, section?: string, full?: boolean) {
  return useQuery({
    queryKey: ["wiki", "page", pageId, section, full],
    queryFn: () => getWikiPage(pageId as string, { section, full }),
    enabled: !!pageId,
  });
}

export function useWikiDrafts() {
  return useQuery({ queryKey: ["wiki", "drafts"], queryFn: getWikiDrafts });
}

export function useWikiDraft(pageId: string | null) {
  return useQuery({
    queryKey: ["wiki", "draft", pageId],
    queryFn: () => getWikiDraft(pageId as string),
    enabled: !!pageId,
  });
}

export function candidatesRefetchInterval(status?: string): number | false {
  return status === "running" ? 2000 : false;
}

export function useWikiCandidates(project: string) {
  return useQuery({
    queryKey: ["wiki", "candidates", project],
    queryFn: () => getWikiCandidates(project),
    refetchInterval: (query) => candidatesRefetchInterval(query.state.data?.status),
  });
}

export function useClassifyCandidates() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (project: string) => startClassify(project),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["wiki", "candidates"] }),
  });
}

function useWikiMutation<V, R>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["wiki"] }),
  });
}

export const useApproveDraft = () => useWikiMutation((pageId: string) => approveDraft(pageId));
export const useRejectDraft = () =>
  useWikiMutation((v: { pageId: string; reason: string }) => rejectDraft(v.pageId, v.reason));
export const useEditDraft = () =>
  useWikiMutation((v: { pageId: string } & DraftEdit) =>
    editDraft(v.pageId, { body: v.body, title: v.title, description: v.description })
  );
export const useCreateDraft = () =>
  useWikiMutation((v: { memoryIds: string[]; pageType: string; title?: string }) =>
    createDraft(v.memoryIds, v.pageType, v.title)
  );
