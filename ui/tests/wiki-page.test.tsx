import { describe, test, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { WikiPageView } from "@/components/wiki/wiki-page";
import fixture from "./fixtures/wiki-page.json";
import { WikiPageSchema } from "@/lib/schemas";

describe("WikiPageView", () => {
  test("renders markdown headings, a TOC, and source links", () => {
    const page = WikiPageSchema.parse(fixture);
    render(<WikiPageView page={page} />);
    expect(screen.getByRole("heading", { name: /rotate gateway key/i })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /2026-01-01_fact_a1/ }).length).toBeGreaterThan(0);
    expect(screen.getByRole("navigation", { name: /on this page/i })).toHaveTextContent(/steps/i);
  });

  test("shows the withdrawn warning when validity is withdrawn", () => {
    const page = WikiPageSchema.parse({ ...fixture, validity: "withdrawn", validity_reasons: ["source disputed"] });
    render(<WikiPageView page={page} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/withdrawn/i);
  });
});

describe("WikiPageView interactions", () => {
  const base = WikiPageSchema.parse(fixture);

  test("clicking a source link calls onOpenSource with the id", () => {
    const onOpenSource = vi.fn();
    render(<WikiPageView page={base} onOpenSource={onOpenSource} />);
    fireEvent.click(screen.getAllByRole("link", { name: /2026-01-01_fact_a1/ })[0]);
    expect(onOpenSource).toHaveBeenCalledWith("2026-01-01_fact_a1");
  });

  test("multi-id source markers yield one link per id", () => {
    const onOpenSource = vi.fn();
    const page = { ...base, body: "## Steps {#steps}\nsee [source: id_a, id_b]" };
    render(<WikiPageView page={page} onOpenSource={onOpenSource} />);
    fireEvent.click(screen.getByRole("link", { name: "id_b" }));
    expect(onOpenSource).toHaveBeenCalledWith("id_b");
    expect(screen.getByRole("link", { name: "id_a" })).toBeInTheDocument();
  });

  test("does not rewrite sources inside code fences or inline code", () => {
    const body = "## Steps {#steps}\n```\n[source: fenced_id]\n```\nuse `[source: inline_id]` here";
    render(<WikiPageView page={{ ...base, body }} />);
    expect(screen.queryByRole("link", { name: /fenced_id|inline_id/ })).toBeNull();
    expect(screen.getByText(/\[source: fenced_id\]/)).toBeInTheDocument();
  });

  test("heading anchors are stripped from the text and used as ids", () => {
    render(<WikiPageView page={base} />);
    const h = screen.getByRole("heading", { name: "Steps" });
    expect(h).toHaveAttribute("id", "steps");
  });

  test("shows the stale badge and alert", () => {
    render(<WikiPageView page={{ ...base, validity: "stale", validity_reasons: ["old"] }} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/stale/i);
  });

  test("shows the over-budget notice", () => {
    render(<WikiPageView page={{ ...base, over_budget: true }} />);
    expect(screen.getByText(/truncated to budget/i)).toBeInTheDocument();
  });

  test("TOC entries open sections and the toggle requests the full page", () => {
    const onOpenSection = vi.fn();
    const onToggleFull = vi.fn();
    render(<WikiPageView page={base} onOpenSection={onOpenSection} full={false} onToggleFull={onToggleFull} />);
    fireEvent.click(within(screen.getByRole("navigation", { name: /on this page/i })).getByText("verify"));
    expect(onOpenSection).toHaveBeenCalledWith("verify");
    fireEvent.click(screen.getByRole("button", { name: /full page/i }));
    expect(onToggleFull).toHaveBeenCalled();
  });
});
