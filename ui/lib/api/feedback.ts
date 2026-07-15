import { fetchJson } from "./client";
import {
  FeedbackResponseSchema,
  type FeedbackResponse,
  type FeedbackVerdict,
} from "@/lib/schemas";

export type { FeedbackVerdict, FeedbackResponse };

export function postFeedback(
  memoryId: string,
  verdict: FeedbackVerdict,
  sessionId?: string
): Promise<FeedbackResponse> {
  return fetchJson(
    "/api/memory/feedback",
    {
      method: "POST",
      body: JSON.stringify({
        memory_id: memoryId,
        verdict,
        ...(sessionId ? { session_id: sessionId } : {}),
      }),
    },
    (d) => FeedbackResponseSchema.parse(d)
  );
}
