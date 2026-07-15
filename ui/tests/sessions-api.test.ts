import { describe, test, expect, vi, afterEach } from "vitest";
import { getSessions, getSessionDetail } from "@/lib/api/sessions";
import { postFeedback } from "@/lib/api/feedback";
import sessionsFixture from "./fixtures/sessions.json";
import sessionDetailFixture from "./fixtures/session-detail.json";

describe("sessions api", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("getSessions hits /api/memory/sessions with limit and parses response", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(sessionsFixture)));
    vi.stubGlobal("fetch", fetchMock);

    const res = await getSessions("", 50);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/memory/sessions?limit=50",
      expect.anything()
    );
    expect(res.sessions).toHaveLength(3);
    expect(res.window).toBe(5000);
  });

  test("getSessions passes the selected scope as ?project=", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(sessionsFixture)));
    vi.stubGlobal("fetch", fetchMock);

    await getSessions("byte-edge", 50);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/memory/sessions?limit=50&project=byte-edge",
      expect.anything()
    );
  });

  test("getSessionDetail hits the id route and parses recalls", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(sessionDetailFixture)));
    vi.stubGlobal("fetch", fetchMock);

    const res = await getSessionDetail("sess-abc123");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/memory/sessions/sess-abc123",
      expect.anything()
    );
    expect(res.recalls).toHaveLength(2);
    expect(res.injected[0].token_estimate).toBeNull();
  });

  test("postFeedback POSTs memory_id + verdict with the UI mutation header", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ recorded: true })));
    vi.stubGlobal("fetch", fetchMock);

    const res = await postFeedback("m1", "useful", "sess-1");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/memory/feedback");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      memory_id: "m1",
      verdict: "useful",
      session_id: "sess-1",
    });
    expect((init.headers as Record<string, string>)["X-Rekall-UI"]).toBe("1");
    expect(res.recorded).toBe(true);
  });
});
