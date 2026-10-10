import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

const mutate = vi.fn();
const classify = vi.fn();
let candidatesData: unknown;

vi.mock("@/lib/queries/use-wiki", () => ({
  useWikiCandidates: () => ({ data: candidatesData, error: null }),
  useClassifyCandidates: () => ({ mutate: classify, isPending: false, error: null }),
  useCreateDraft: () => ({ mutate, isPending: false, data: undefined, error: null }),
}));

import { WikiCandidates } from "@/components/wiki/wiki-candidates";

const cand = (id: string, page_type: string) => ({
  memory_id: id, content: `content ${id}`, question: `q ${id}`, page_type, scope: null, reasons: ["r"],
});

beforeEach(() => {
  mutate.mockClear();
  classify.mockClear();
});

describe("WikiCandidates", () => {
  test("classify button triggers the classify mutation with the project; unconfigured is explained", () => {
    candidatesData = { status: "unconfigured", candidates: [] };
    render(<WikiCandidates project="demo" />);
    expect(screen.getByText(/not configured/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^classify$/i }));
    expect(classify).toHaveBeenCalledWith("demo");
  });

  test("drafts the selected candidates", () => {
    candidatesData = { status: "done", candidates: [cand("a", "process"), cand("b", "process")] };
    render(<WikiCandidates project="demo" />);
    fireEvent.click(screen.getByLabelText("Select a"));
    fireEvent.click(screen.getByLabelText("Select b"));
    fireEvent.click(screen.getByRole("button", { name: /draft selected/i }));
    expect(mutate.mock.calls[0][0]).toEqual({ memoryIds: ["a", "b"], pageType: "process" });
  });

  test("mixed page types disable drafting with a message", () => {
    candidatesData = { status: "done", candidates: [cand("a", "process"), cand("b", "policy")] };
    render(<WikiCandidates project="demo" />);
    fireEvent.click(screen.getByLabelText("Select a"));
    fireEvent.click(screen.getByLabelText("Select b"));
    expect(screen.getByRole("button", { name: /draft selected/i })).toBeDisabled();
    expect(screen.getByText(/same page type/i)).toBeInTheDocument();
  });

  test("shows cached candidates from GET without any classify click", () => {
    candidatesData = { status: "idle", candidates: [cand("a", "process")] };
    render(<WikiCandidates project="demo" />);
    expect(screen.getByLabelText("Select a")).toBeInTheDocument();
    expect(classify).not.toHaveBeenCalled();
  });

  test("running shows progress and disables the button", () => {
    candidatesData = { status: "running", done: 12, total: 60, candidates: [] };
    render(<WikiCandidates project="demo" />);
    expect(screen.getByRole("button", { name: /classifying 12\/60/i })).toBeDisabled();
  });

  test("job error shows the message", () => {
    candidatesData = { status: "error", error: "model unreachable: 3 consecutive failures", done: 3, total: 9, candidates: [] };
    render(<WikiCandidates project="demo" />);
    expect(screen.getByText(/model unreachable/i)).toBeInTheDocument();
  });
});
