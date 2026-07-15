import { useMutation } from "@tanstack/react-query";
import {
  postFeedback,
  type FeedbackResponse,
  type FeedbackVerdict,
} from "@/lib/api/feedback";

// Extracted from app/sessions/page.tsx (inline postFeedback call) — behavior
// covered by the green feedback cycles in sessions.test.tsx. No new behavior.
export function useFeedbackMutation() {
  return useMutation<
    FeedbackResponse,
    Error,
    { memoryId: string; verdict: FeedbackVerdict; sessionId?: string }
  >({
    mutationFn: ({ memoryId, verdict, sessionId }) =>
      postFeedback(memoryId, verdict, sessionId),
  });
}
