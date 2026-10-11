import { describe, test, expect, vi, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { createQueryClient } from "@/lib/query-client";
import { useWikiDraft } from "@/lib/queries/use-wiki";
import { useStream } from "@/lib/queries/use-stream";

afterEach(() => vi.unstubAllGlobals());

function wrapper() {
  const client = createQueryClient();
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

function stubStatus(status: number) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ error: "nope" }), { status }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("default query client never retries 4xx", () => {
  test("wiki draft 404 is fetched once", async () => {
    const fetchMock = stubStatus(404);
    const { result } = renderHook(() => useWikiDraft("demo/policy/x"), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  test("stream 400 is fetched once", async () => {
    const fetchMock = stubStatus(400);
    const { result } = renderHook(() => useStream("demo", 50, { after: "bad" }), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
