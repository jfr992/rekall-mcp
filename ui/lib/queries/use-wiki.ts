import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  approveDraft,
  createDraft,
  editDraft,
  getWikiCandidates,
  getWikiDrafts,
  getWikiIndex,
  getWikiPage,
  rejectDraft,
  searchWiki,
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

export function useWikiCandidates(project: string) {
  return useQuery({
    queryKey: ["wiki", "candidates", project],
    queryFn: () => getWikiCandidates(project),
    enabled: false,
    staleTime: Infinity,
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
  useWikiMutation((v: { pageId: string; body: string }) => editDraft(v.pageId, v.body));
export const useCreateDraft = () =>
  useWikiMutation((v: { memoryIds: string[]; pageType: string; title?: string }) =>
    createDraft(v.memoryIds, v.pageType, v.title)
  );
