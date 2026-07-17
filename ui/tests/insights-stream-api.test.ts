import { describe, test, expect, vi, afterEach } from "vitest";
import { getInsights } from "@/lib/api/insights";
import { getStream } from "@/lib/api/stream";
import insightsFixture from "./fixtures/insights.json";
import streamFixture from "./fixtures/stream.json";

describe("insights + stream api", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("getInsights hits /api/memory/insights with the scope and parses", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(insightsFixture)));
    vi.stubGlobal("fetch", fetchMock);

    const res = await getInsights("byte-edge");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/memory/insights?project=byte-edge",
      expect.anything()
    );
    expect(res.in_scope).toBe(41);
    expect(res.event_window.events).toBe(5000);
  });

  test("getStream hits /api/memory/stream with limit + scope and parses kinds", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(streamFixture)));
    vi.stubGlobal("fetch", fetchMock);

    const res = await getStream("byte-edge", 50);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/memory/stream?limit=50&project=byte-edge",
      expect.anything()
    );
    expect(res.rows).toHaveLength(5);
    expect(res.rows[0].kind).toBe("saved");
  });
});
