import { expect, test, vi } from "vitest";
import { getWikiDrafts } from "@/lib/api/wiki";

test("getWikiDrafts scopes by project", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ drafts: [] })));
  vi.stubGlobal("fetch", fetchMock);
  await getWikiDrafts("demo");
  expect(String(fetchMock.mock.calls[0][0])).toContain("/api/wiki/drafts?project=demo");
});
