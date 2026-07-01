import { describe, it, expect } from "vitest";
import { PublishResponseSchema } from "@/lib/schemas";

describe("PublishResponseSchema", () => {
  it("parses a valid publish response", () => {
    const ok = PublishResponseSchema.parse({
      tree: ["a/b.md"],
      files: { "a/b.md": "---\ntype: runbook\n---\nx" },
      stats: { concepts: 1, clusters: 1, titled_by: "slug" },
    });
    expect(ok.tree.length).toBe(1);
  });

  it("rejects missing tree", () => {
    expect(() => PublishResponseSchema.parse({ files: {}, stats: {} })).toThrow();
  });
});
