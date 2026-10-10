import { describe, test, expect } from "vitest";
import { render, screen } from "@testing-library/react";
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
