import { describe, it, expect, vi, afterEach } from "vitest";
import { fetchJson } from "@/lib/api/client";

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
