import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import indexFixture from "./fixtures/wiki-index.json";
import pageFixture from "./fixtures/wiki-page.json";
import draftsFixture from "./fixtures/wiki-drafts.json";
import draftFixture from "./fixtures/wiki-draft.json";
import { WikiIndexSchema, WikiPageSchema, WikiDraftsSchema, WikiDraftDetailSchema } from "@/lib/schemas";

vi.mock("@/lib/project-store", () => ({
  useProjectStore: vi.fn((sel: any) => sel({ project: "demo", setProject: vi.fn() })),
}));
vi.mock("@/lib/queries/use-memory-detail", () => ({ useMemoryDetail: vi.fn(() => ({ data: undefined, isLoading: true })) }));
vi.mock("@/components/memory-inspector/memory-inspector", () => ({
  MemoryInspector: ({ open }: { open: boolean }) => (open ? <div>inspector-open</div> : null),
}));
vi.mock("@/lib/queries/use-wiki", () => {
  const q = (data: unknown) => ({ data, isLoading: false, isError: false });
  const m = () => ({ mutate: vi.fn(), isPending: false });
  const approveMutate = vi.fn();
  return {
    useWikiIndex: () => q(WikiIndexSchema.parse(indexFixture)),
    useWikiPage: (id: string | null) => (id ? q(WikiPageSchema.parse(pageFixture)) : q(undefined)),
    useWikiDrafts: () => q(WikiDraftsSchema.parse(draftsFixture)),
    useWikiDraft: (id: string | null) => (id ? q(WikiDraftDetailSchema.parse(draftFixture)) : q(undefined)),
    useWikiSearch: () => q(undefined),
    useWikiCandidates: () => ({ data: undefined, mutate: vi.fn(), isPending: false, error: null }),
    useApproveDraft: () => ({ mutate: approveMutate, isPending: false }), __approveMutate: approveMutate, useRejectDraft: m, useEditDraft: m, useCreateDraft: () => ({ ...m(), data: undefined, error: null }),
  };
});

import { useMemoryDetail } from "@/lib/queries/use-memory-detail";
import * as wikiQueries from "@/lib/queries/use-wiki";
import WikiRoute from "@/app/wiki/page";

beforeEach(() => vi.mocked(useMemoryDetail).mockClear());

describe("/wiki route", () => {
  test("wiki route does not render a second <main>", () => {
    const { container } = render(<WikiRoute />);
    expect(container.querySelector("main")).toBeNull();
  });

  test("clicking a source opens the memory inspector for that id", () => {
    render(<WikiRoute />);
    fireEvent.click(screen.getByText(/rotate gateway key/i));
    fireEvent.click(screen.getAllByRole("link", { name: /2026-01-01_fact_a1/ })[0]);
    expect(vi.mocked(useMemoryDetail)).toHaveBeenLastCalledWith("2026-01-01_fact_a1");
    expect(screen.getByText("inspector-open")).toBeInTheDocument();
  });

  test("Open on a draft renders the draft body with approve/reject", () => {
    render(<WikiRoute />);
    fireEvent.click(screen.getByRole("button", { name: /^drafts/i }));
    fireEvent.click(screen.getByRole("button", { name: /open/i }));
    expect(screen.getByText(/always add a trailer/i)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /approve/i }).length).toBeGreaterThan(1);
  });

  test("approving a draft with missing sections asks first", () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const approveMutate = (wikiQueries as unknown as { __approveMutate: ReturnType<typeof vi.fn> }).__approveMutate;
    approveMutate.mockClear();
    render(<WikiRoute />);
    fireEvent.click(screen.getByRole("button", { name: /^drafts/i }));
    fireEvent.click(screen.getAllByRole("button", { name: /approve/i })[0]);
    expect(confirm).toHaveBeenCalledWith(expect.stringMatching(/exceptions/));
    expect(approveMutate).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  test("approving with confirm accepted calls approve", () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const approveMutate = (wikiQueries as unknown as { __approveMutate: ReturnType<typeof vi.fn> }).__approveMutate;
    approveMutate.mockClear();
    render(<WikiRoute />);
    fireEvent.click(screen.getByRole("button", { name: /^drafts/i }));
    fireEvent.click(screen.getAllByRole("button", { name: /approve/i })[0]);
    expect(approveMutate).toHaveBeenCalledWith("demo/policy/commits", expect.anything());
    confirm.mockRestore();
  });
});
