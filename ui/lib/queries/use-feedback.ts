import { useMutation, useQueryClient } from "@tanstack/react-query";
import { invalidateMemoryCaches } from "@/lib/queries/invalidate";
import {
  postFeedback,
  type FeedbackResponse,
  type FeedbackVerdict,
} from "@/lib/api/feedback";

// Extracted from app/sessions/page.tsx (inline postFeedback call) — behavior
// covered by the green feedback cycles in sessions.test.tsx. No new behavior.
export function useFeedbackMutation() {
  const qc = useQueryClient();
  return useMutation<
    FeedbackResponse,
    Error,
    { memoryId: string; verdict: FeedbackVerdict; sessionId?: string }
  >({
    mutationFn: ({ memoryId, verdict, sessionId }) =>
      postFeedback(memoryId, verdict, sessionId),
    onSuccess: () => invalidateMemoryCaches(qc),
  });
}
