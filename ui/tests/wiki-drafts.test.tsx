import { describe, test, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { WikiDraftsList } from "@/components/wiki/wiki-drafts";
import fixture from "./fixtures/wiki-drafts.json";
import { WikiDraftsSchema } from "@/lib/schemas";

describe("WikiDraftsList", () => {
  test("lists drafts with needs and wires approve and reject", () => {
    const data = WikiDraftsSchema.parse(fixture);
    const onApprove = vi.fn();
    const onReject = vi.fn();
    render(<WikiDraftsList drafts={data.drafts} onApprove={onApprove} onReject={onReject} onOpen={() => {}} />);
    expect(screen.getByText(/needs: exceptions/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /approve/i }));
    expect(onApprove).toHaveBeenCalledWith("demo/policy/commits");
    fireEvent.click(screen.getByRole("button", { name: /reject/i }));
    expect(onReject).toHaveBeenCalledWith("demo/policy/commits");
  });
});

describe("WikiDraftsList gating", () => {
  const draft = WikiDraftsSchema.parse(fixture).drafts[0];
  test.each([
    ["redaction", { has_redaction: true }],
    ["unsourced steps", { unsourced_steps: 2 }],
  ])("Approve is disabled for %s", (_n, patch) => {
    const onApprove = vi.fn();
    render(<WikiDraftsList drafts={[{ ...draft, ...patch }]} onApprove={onApprove} onReject={() => {}} onOpen={() => {}} />);
    const btn = screen.getByRole("button", { name: /approve/i });
    expect(btn).toBeDisabled();
    fireEvent.click(btn);
    expect(onApprove).not.toHaveBeenCalled();
  });

  test("Open reports the page id", () => {
    const onOpen = vi.fn();
    render(<WikiDraftsList drafts={[draft]} onApprove={() => {}} onReject={() => {}} onOpen={onOpen} />);
    fireEvent.click(screen.getByRole("button", { name: /open/i }));
    expect(onOpen).toHaveBeenCalledWith("demo/policy/commits");
  });
});
