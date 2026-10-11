import { describe, expect, test, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("@/lib/api/wiki", () => ({
  approveDraft: vi.fn().mockResolvedValue({}),
  rejectDraft: vi.fn().mockResolvedValue({}),
  editDraft: vi.fn().mockResolvedValue({}),
  createDraft: vi.fn().mockResolvedValue({}),
}));

import { useApproveDraft, useEditDraft, useRejectDraft } from "@/lib/queries/use-wiki";

function setup() {
  const client = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const remove = vi.spyOn(client, "removeQueries");
  const invalidate = vi.spyOn(client, "invalidateQueries");
  return { wrapper, remove, invalidate };
}

describe("wiki draft mutations", () => {
  test("edit keeps the draft query (no skeleton flash) and still invalidates wiki", async () => {
    const { wrapper, remove, invalidate } = setup();
    const { result } = renderHook(() => useEditDraft(), { wrapper });
    await act(async () => {
      result.current.mutate({ pageId: "p", body: "b", title: "t", description: "d" });
    });
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["wiki"] }));
    expect(remove).not.toHaveBeenCalled();
  });

  test.each([
    ["approve", () => useApproveDraft(), "p"],
    ["reject", () => useRejectDraft(), { pageId: "p", reason: "r" }],
  ])("%s removes the draft query", async (_n, hook, arg) => {
    const { wrapper, remove } = setup();
    const { result } = renderHook(hook as () => { mutate: (v: unknown) => void }, { wrapper });
    await act(async () => {
      result.current.mutate(arg);
    });
    await waitFor(() => expect(remove).toHaveBeenCalledWith({ queryKey: ["wiki", "draft"] }));
  });
});
