import { describe, test, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { KbColumns } from "@/components/kb/kb-columns";
import kbFixture from "./fixtures/kb.json";
import { KbResponseSchema } from "@/lib/schemas";

describe("KbColumns", () => {
  test("renders four slice headers and their counts", () => {
    const data = KbResponseSchema.parse(kbFixture);
    render(<KbColumns data={data} />);
    expect(screen.getByRole("heading", { name: /decisions/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /requirements/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /preferences/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /learnings/i })).toBeInTheDocument();
  });

  test("renders entries from fixture", () => {
    const data = KbResponseSchema.parse(kbFixture);
    render(<KbColumns data={data} />);
    expect(screen.getByText(/behavioral tiering/i)).toBeInTheDocument();
    expect(screen.getByText(/terse responses/i)).toBeInTheDocument();
  });
});
