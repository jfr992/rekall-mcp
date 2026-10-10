import { describe, test, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { WikiDraftView } from "@/components/wiki/wiki-draft-view";
import { WikiDraftDetailSchema } from "@/lib/schemas";
import fixture from "./fixtures/wiki-draft.json";

describe("WikiDraftView", () => {
  const draft = WikiDraftDetailSchema.parse(fixture);

  test("renders the draft body with approve and reject beside it", () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();
    render(<WikiDraftView draft={draft} onApprove={onApprove} onReject={onReject} />);
    expect(screen.getByText(/always add a trailer/i)).toBeInTheDocument();
    expect(screen.getByText(/needs: exceptions/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /approve/i }));
    expect(onApprove).toHaveBeenCalledWith("demo/policy/commits");
    fireEvent.click(screen.getByRole("button", { name: /reject/i }));
    expect(onReject).toHaveBeenCalledWith("demo/policy/commits");
  });

  test("approve is disabled with redaction", () => {
    render(<WikiDraftView draft={{ ...draft, has_redaction: true }} onApprove={() => {}} onReject={() => {}} />);
    expect(screen.getByRole("button", { name: /approve/i })).toBeDisabled();
  });

  test("edit shows body, title and description inputs and Save sends them", () => {
    const onSave = vi.fn();
    render(
      <WikiDraftView
        draft={{ ...draft, description: "How to add trailers" }}
        onApprove={() => {}}
        onReject={() => {}}
        onSave={onSave}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /^edit$/i }));
    fireEvent.change(screen.getByLabelText(/^body$/i), { target: { value: "## Rule {#rule}\nnew rule" } });
    fireEvent.change(screen.getByLabelText(/^title$/i), { target: { value: "New title" } });
    expect(screen.getByLabelText(/^description$/i)).toHaveValue("How to add trailers");
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(onSave).toHaveBeenCalledWith({
      pageId: "demo/policy/commits",
      body: "## Rule {#rule}\nnew rule",
      title: "New title",
      description: "How to add trailers",
    });
  });
});
