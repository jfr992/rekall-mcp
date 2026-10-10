import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

const mutate = vi.fn();
const refetch = vi.fn();
let candidatesData: unknown;

vi.mock("@/lib/queries/use-wiki", () => ({
  useWikiCandidates: () => ({ data: candidatesData, refetch, isFetching: false, error: null }),
  useCreateDraft: () => ({ mutate, isPending: false, data: undefined, error: null }),
}));

import { WikiCandidates } from "@/components/wiki/wiki-candidates";

const cand = (id: string, page_type: string) => ({
  memory_id: id, content: `content ${id}`, question: `q ${id}`, page_type, scope: null, reasons: ["r"],
});

beforeEach(() => {
  mutate.mockClear();
  refetch.mockClear();
});

describe("WikiCandidates", () => {
  test("classify button triggers refetch; unconfigured is explained", () => {
    candidatesData = { status: "unconfigured" };
    render(<WikiCandidates project="demo" />);
    expect(screen.getByText(/not configured/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /classify candidates/i }));
    expect(refetch).toHaveBeenCalled();
  });

  test("drafts the selected candidates", () => {
    candidatesData = { candidates: [cand("a", "process"), cand("b", "process")] };
    render(<WikiCandidates project="demo" />);
    fireEvent.click(screen.getByLabelText("Select a"));
    fireEvent.click(screen.getByLabelText("Select b"));
    fireEvent.click(screen.getByRole("button", { name: /draft selected/i }));
    expect(mutate.mock.calls[0][0]).toEqual({ memoryIds: ["a", "b"], pageType: "process" });
  });

  test("mixed page types disable drafting with a message", () => {
    candidatesData = { candidates: [cand("a", "process"), cand("b", "policy")] };
    render(<WikiCandidates project="demo" />);
    fireEvent.click(screen.getByLabelText("Select a"));
    fireEvent.click(screen.getByLabelText("Select b"));
    expect(screen.getByRole("button", { name: /draft selected/i })).toBeDisabled();
    expect(screen.getByText(/same page type/i)).toBeInTheDocument();
  });
});
