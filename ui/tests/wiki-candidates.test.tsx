import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

const mutate = vi.fn();
const classify = vi.fn();
const onOpenSource = vi.fn();
let candidatesData: unknown;

vi.mock("@/lib/queries/use-wiki", () => ({
  useWikiCandidates: () => ({ data: candidatesData, error: null }),
  useClassifyCandidates: () => ({ mutate: classify, isPending: false, error: null }),
  useCreateDraft: () => ({ mutate, isPending: false, data: undefined, error: null }),
}));

import { WikiCandidates } from "@/components/wiki/wiki-candidates";

const cand = (id: string, page_type: string, extra: Record<string, unknown> = {}) => ({
  memory_id: id, content: `content ${id}`, question: `q ${id}`, page_type, scope: null, reasons: ["r"],
  project: "demo", date: "2026-03-05", used_in: [], ...extra,
});

beforeEach(() => {
  mutate.mockClear();
  classify.mockClear();
  onOpenSource.mockClear();
});

describe("WikiCandidates", () => {
  test("classify button triggers the classify mutation with the project; unconfigured is explained", () => {
    candidatesData = { status: "unconfigured", candidates: [] };
    render(<WikiCandidates project="demo" onOpenSource={onOpenSource} />);
    expect(screen.getByText(/not configured/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^classify$/i }));
    expect(classify).toHaveBeenCalledWith("demo");
  });

  test("drafts the selected candidates", () => {
    candidatesData = { status: "done", candidates: [cand("a", "process"), cand("b", "process")] };
    render(<WikiCandidates project="demo" onOpenSource={onOpenSource} />);
    fireEvent.click(screen.getByLabelText("Select a"));
    fireEvent.click(screen.getByLabelText("Select b"));
    fireEvent.click(screen.getByRole("button", { name: /^draft as/i }));
    expect(mutate.mock.calls[0][0]).toEqual({ memoryIds: ["a", "b"], pageType: "process" });
  });

  test("mixed page types disable drafting with a message", () => {
    candidatesData = { status: "done", candidates: [cand("a", "process"), cand("b", "policy")] };
    render(<WikiCandidates project="demo" onOpenSource={onOpenSource} />);
    fireEvent.click(screen.getByLabelText("Select a"));
    fireEvent.click(screen.getByLabelText("Select b"));
    expect(screen.getByRole("button", { name: /^draft as/i })).toBeDisabled();
    expect(screen.getByText(/same page type/i)).toBeInTheDocument();
  });

  test("shows cached candidates from GET without any classify click", () => {
    candidatesData = { status: "idle", candidates: [cand("a", "process")] };
    render(<WikiCandidates project="demo" onOpenSource={onOpenSource} />);
    expect(screen.getByLabelText("Select a")).toBeInTheDocument();
    expect(classify).not.toHaveBeenCalled();
  });

  test("running shows progress and disables the button", () => {
    candidatesData = { status: "running", done: 12, total: 60, candidates: [] };
    render(<WikiCandidates project="demo" onOpenSource={onOpenSource} />);
    expect(screen.getByRole("button", { name: /classifying 12\/60/i })).toBeDisabled();
  });

  test("job error shows the message", () => {
    candidatesData = { status: "error", error: "model unreachable: 3 consecutive failures", done: 3, total: 9, candidates: [] };
    render(<WikiCandidates project="demo" onOpenSource={onOpenSource} />);
    expect(screen.getByText(/model unreachable/i)).toBeInTheDocument();
  });

  const mixed = () => {
    candidatesData = {
      status: "done",
      candidates: [
        cand("a", "process", { question: "rotate key", date: "2026-03-05", project: "alpha" }),
        cand("b", "process", { question: "deploy gate" }),
        cand("c", "policy", { question: "retention", reasons: ["compliance"] }),
        cand("u", "process", { question: "already used", used_in: ["demo/process/p1"] }),
      ],
    };
    render(<WikiCandidates project="demo" onOpenSource={onOpenSource} />);
  };

  test("text filter narrows by question, content, reasons and id", () => {
    mixed();
    fireEvent.change(screen.getByPlaceholderText(/filter/i), { target: { value: "COMPLIANCE" } });
    expect(screen.getByLabelText("Select c")).toBeInTheDocument();
    expect(screen.queryByLabelText("Select a")).toBeNull();
  });

  test("type chips narrow the list and counts follow the text filter", () => {
    mixed();
    expect(screen.getByRole("button", { name: /^process 2$/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^policy 1$/i }));
    expect(screen.queryByLabelText("Select a")).toBeNull();
    expect(screen.getByLabelText("Select c")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^all/i }));
    fireEvent.change(screen.getByPlaceholderText(/filter/i), { target: { value: "rotate" } });
    expect(screen.getByRole("button", { name: /^process 1$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^policy 0$/i })).toBeInTheDocument();
  });

  test("hide used is on by default; toggling shows the page it is used in", () => {
    mixed();
    expect(screen.queryByLabelText("Select u")).toBeNull();
    fireEvent.click(screen.getByLabelText(/hide used/i));
    expect(screen.getByLabelText("Select u")).toBeInTheDocument();
    expect(screen.getByText("in demo/process/p1")).toBeInTheDocument();
  });

  test("select all visible only appears with a type chip and selects just the filtered items", () => {
    mixed();
    expect(screen.queryByRole("button", { name: /select all visible/i })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^process 2$/i }));
    fireEvent.click(screen.getByRole("button", { name: /select all visible/i }));
    expect(screen.getByLabelText("Select a")).toBeChecked();
    expect(screen.getByLabelText("Select b")).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: /^draft as process/i }));
    expect(mutate.mock.calls[0][0]).toEqual({ memoryIds: ["a", "b"], pageType: "process" });
  });

  test("sticky bar shows the count and clears", () => {
    mixed();
    expect(screen.queryByText(/selected/i)).toBeNull();
    fireEvent.click(screen.getByLabelText("Select c"));
    expect(screen.getByText(/1 selected/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^clear$/i }));
    expect(screen.queryByText(/1 selected/i)).toBeNull();
  });

  test("meta line shows date and project; show memory opens the source", () => {
    mixed();
    expect(screen.getByText(/2026-03-05 · alpha · process/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /show memory/i })[0]);
    expect(onOpenSource).toHaveBeenCalledWith("a");
  });

  test("empty filter result offers clear filters", () => {
    mixed();
    fireEvent.change(screen.getByPlaceholderText(/filter/i), { target: { value: "zzzz" } });
    expect(screen.getByText(/no candidates match/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /clear filters/i }));
    expect(screen.getByLabelText("Select a")).toBeInTheDocument();
  });

  test("picks hidden by a filter change are not counted or drafted", () => {
    mixed();
    fireEvent.click(screen.getByLabelText("Select a"));
    fireEvent.click(screen.getByLabelText("Select c"));
    fireEvent.change(screen.getByPlaceholderText(/filter/i), { target: { value: "rotate" } });
    expect(screen.getByText("1 selected · +1 hidden")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^draft as process/i }));
    expect(mutate.mock.calls[0][0]).toEqual({ memoryIds: ["a"], pageType: "process" });
  });

  test("clear filters also resets hide used, and the empty state says why", () => {
    candidatesData = { status: "done", candidates: [cand("u", "process", { used_in: ["demo/process/p1"] })] };
    render(<WikiCandidates project="demo" onOpenSource={onOpenSource} />);
    expect(screen.getByText(/1 hidden as already used/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /clear filters/i }));
    expect(screen.getByLabelText("Select u")).toBeInTheDocument();
    expect(screen.getByLabelText(/hide used/i)).not.toBeChecked();
  });
});
