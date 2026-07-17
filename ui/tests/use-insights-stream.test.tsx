import { describe, test, expect, vi } from "vitest";
import React from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import insightsFixture from "./fixtures/insights.json";

import streamFixture from "./fixtures/stream.json";

vi.mock("@/lib/api/insights", async () => {
  const fixture = (await import("./fixtures/insights.json")).default;
  return { getInsights: vi.fn().mockResolvedValue(fixture) };
});

vi.mock("@/lib/api/stream", async () => {
  const fixture = (await import("./fixtures/stream.json")).default;
  return { getStream: vi.fn().mockResolvedValue(fixture) };
});

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useInsights", () => {
  test("fetches the scoped insights payload", async () => {
    const { useInsights } = await import("@/lib/queries/use-insights");
    const { getInsights } = await import("@/lib/api/insights");

    const { result } = renderHook(() => useInsights("byte-edge"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(getInsights).toHaveBeenCalledWith("byte-edge");
    expect(result.current.data?.in_scope).toBe(insightsFixture.in_scope);
  });
});

describe("useStream", () => {
  test("fetches the stream feed and polls every 10s", async () => {
    const { useStream } = await import("@/lib/queries/use-stream");
    const { getStream } = await import("@/lib/api/stream");

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const clientWrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useStream("byte-edge", 50), {
      wrapper: clientWrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(getStream).toHaveBeenCalledWith("byte-edge", 50);
    expect(result.current.data?.rows).toHaveLength(streamFixture.rows.length);
    // one poll per page, panels derive from this cache (PLAN: no SSE)
    const query = client.getQueryCache().find({ queryKey: ["stream", "byte-edge", 50] });
    expect(query?.observers[0]?.options.refetchInterval).toBe(10_000);
  });
});
