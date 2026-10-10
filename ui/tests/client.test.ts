import { describe, it, expect, vi, afterEach } from "vitest";
import { fetchJson, ApiError, apiErrorMessage } from "@/lib/api/client";

function mockFetch() {
  const fn = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ ok: true }),
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchJson browser-guard header", () => {
  it("sends X-Rekall-UI on mutations", async () => {
    const fn = mockFetch();
    await fetchJson("/api/memory/prune/plan", {
      method: "POST",
      body: JSON.stringify({ project: "p" }),
    });
    const init = fn.mock.calls[0][1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Rekall-UI"]).toBe("1");
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("does not send X-Rekall-UI on reads", async () => {
    const fn = mockFetch();
    await fetchJson("/api/memory/stats");
    const headers = (fn.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
    expect(headers["X-Rekall-UI"]).toBeUndefined();
  });

  it("caller-supplied headers extend, never clobber, the defaults", async () => {
    const fn = mockFetch();
    await fetchJson("/api/x", { method: "POST", headers: { "X-Extra": "y" } });
    const headers = (fn.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
    expect(headers["X-Rekall-UI"]).toBe("1");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(headers["X-Extra"]).toBe("y");
  });
});

describe("apiErrorMessage", () => {
  it("prefers the backend error detail from the response body", () => {
    const err = new ApiError(400, "Request failed: 400", { error: "project is required" });
    expect(apiErrorMessage(err)).toBe("project is required");
  });

  it("falls back to the Error message when there is no body detail", () => {
    expect(apiErrorMessage(new ApiError(500, "Request failed: 500", "oops"))).toBe(
      "Request failed: 500"
    );
    expect(apiErrorMessage(new Error("boom"))).toBe("boom");
  });

  it("handles non-Error throwables", () => {
    expect(apiErrorMessage("weird")).toBe("Unexpected error");
  });
});

describe("fetchJson error bodies", () => {
  it("keeps a non-JSON error body as text instead of re-reading the stream", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("Bad Gateway", { status: 502 }))
    );
    const err = (await fetchJson("/api/x").catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(502);
    expect(err.body).toBe("Bad Gateway");
  });

  it("parses a JSON error body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response('{"error":"nope"}', { status: 400 }))
    );
    const err = (await fetchJson("/api/x").catch((e) => e)) as ApiError;
    expect(err.body).toEqual({ error: "nope" });
  });
});
