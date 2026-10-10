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
