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
  return {
    useWikiIndex: () => q(WikiIndexSchema.parse(indexFixture)),
    useWikiPage: (id: string | null) => (id ? q(WikiPageSchema.parse(pageFixture)) : q(undefined)),
    useWikiDrafts: () => q(WikiDraftsSchema.parse(draftsFixture)),
    useWikiDraft: (id: string | null) => (id ? q(WikiDraftDetailSchema.parse(draftFixture)) : q(undefined)),
    useWikiSearch: () => q(undefined),
    useWikiCandidates: () => ({ ...q(undefined), refetch: vi.fn(), isFetching: false, error: null }),
    useApproveDraft: m, useRejectDraft: m, useCreateDraft: () => ({ ...m(), data: undefined, error: null }),
  };
});

import { useMemoryDetail } from "@/lib/queries/use-memory-detail";
import WikiRoute from "@/app/wiki/page";

beforeEach(() => vi.mocked(useMemoryDetail).mockClear());

describe("/wiki route", () => {
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
});
