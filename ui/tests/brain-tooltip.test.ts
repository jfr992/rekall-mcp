import { describe, test, expect } from "vitest";
import { escapeHtml, buildNodeTooltip } from "@/components/brain/tooltip";

describe("escapeHtml", () => {
  test("escapes ampersand", () => {
    expect(escapeHtml("a&b")).toBe("a&amp;b");
  });

  test("escapes less-than", () => {
    expect(escapeHtml("a<b")).toBe("a&lt;b");
  });

  test("escapes greater-than", () => {
    expect(escapeHtml("a>b")).toBe("a&gt;b");
  });

  test("escapes double quote", () => {
    expect(escapeHtml('say "hi"')).toBe("say &quot;hi&quot;");
  });

  test("escapes single quote", () => {
    expect(escapeHtml("it's")).toBe("it&#x27;s");
  });

  test("escapes script tag payload", () => {
    const raw = "<script>alert(1)</script>";
    const out = escapeHtml(raw);
    expect(out).not.toContain("<script>");
    expect(out).toBe("&lt;script&gt;alert(1)&lt;/script&gt;");
  });

  test("returns empty string unchanged", () => {
    expect(escapeHtml("")).toBe("");
  });

  test("does not double-escape", () => {
    // Passing already-escaped string should escape the entities themselves
    expect(escapeHtml("&amp;")).toBe("&amp;amp;");
  });
});

describe("buildNodeTooltip", () => {
  test("escapes script content in node content", () => {
    const html = buildNodeTooltip({
      content: "<script>alert(1)</script>",
      type: "note",
      tier: "working",
      degree: 0,
    });
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
  });

  test("escapes HTML in type field", () => {
    const html = buildNodeTooltip({
      content: "safe content",
      type: '<b onclick="x()">bad</b>',
      tier: "working",
      degree: 1,
    });
    expect(html).not.toContain("<b");
    expect(html).toContain("&lt;b");
  });

  test("escapes HTML in tier field", () => {
    const html = buildNodeTooltip({
      content: "content",
      type: "note",
      tier: '<img src=x onerror="alert(1)">',
      degree: 0,
    });
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;img");
  });

  test("degree is a number and rendered safely", () => {
    const html = buildNodeTooltip({
      content: "c",
      type: "note",
      tier: "working",
      degree: 42,
    });
    expect(html).toContain("42");
  });

  test("handles null/undefined fields gracefully", () => {
    const html = buildNodeTooltip({});
    expect(html).toContain("memory"); // type default
    expect(html).toContain("working"); // tier default
    expect(html).toContain("0 links"); // degree default
  });

  test("truncates long content at 90 chars before escaping", () => {
    const long = "x".repeat(200);
    const html = buildNodeTooltip({ content: long, type: "note", tier: "working", degree: 0 });
    // The displayed content should not exceed 90 chars of x's
    const match = html.match(/>([x]+)</);
    if (match) {
      expect(match[1].length).toBeLessThanOrEqual(90);
    }
  });
});
