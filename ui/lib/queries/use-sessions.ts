import { useQuery } from "@tanstack/react-query";
import { getSessions, getSessionDetail } from "@/lib/api/sessions";

export function useSessions(limit = 50) {
  return useQuery({
    queryKey: ["sessions", limit],
    queryFn: () => getSessions(limit),
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
