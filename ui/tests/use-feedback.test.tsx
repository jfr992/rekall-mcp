import { expect, test, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("@/lib/api/feedback", () => ({ postFeedback: vi.fn().mockResolvedValue({ recorded: true }) }));

import { useFeedbackMutation } from "@/lib/queries/use-feedback";

test("successful verdict invalidates memory caches so a disputed memory refreshes", async () => {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(() => useFeedbackMutation(), { wrapper });
  await act(async () => {
    result.current.mutate({ memoryId: "m1", verdict: "wrong" });
  });
  await waitFor(() => {
    const keys = invalidate.mock.calls.map((c) => (c[0] as { queryKey: unknown[] }).queryKey[0]);
    expect(keys).toEqual(expect.arrayContaining(["memory-detail", "kb", "search"]));
  });
});
