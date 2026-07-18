import { useQuery } from "@tanstack/react-query";
import { getSessions, getSessionDetail, type SessionsRange } from "@/lib/api/sessions";

export function useSessions(project: string, limit = 50, range: SessionsRange = {}) {
  return useQuery({
    queryKey: ["sessions", project, limit, range.after ?? null, range.before ?? null],
    queryFn: () => getSessions(project, limit, range),
    staleTime: 30_000,
  });
}

// Extracted from app/sessions/page.tsx (inline useQuery) — behavior covered by
// the green sessions.test.tsx detail cycles. No new behavior.
export function useSessionDetail(sessionId: string | null) {
  return useQuery({
    queryKey: ["session-detail", sessionId],
    queryFn: () => getSessionDetail(sessionId as string),
    enabled: Boolean(sessionId),
    staleTime: 30_000,
  });
}
