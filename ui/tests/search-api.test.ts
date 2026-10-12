import { expect, test, vi } from "vitest";
import { postRecall } from "@/lib/api/search";

test("postRecall marks the request as a UI search", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify({ query: "q", count: 0, memories: [] })));
  vi.stubGlobal("fetch", fetchMock);
  await postRecall("q", "proj", 10);
  expect(JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string).source).toBe("ui");
});
