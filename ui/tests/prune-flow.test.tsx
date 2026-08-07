import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import HygienePage from "@/app/hygiene/page";
import { useProjectStore } from "@/lib/project-store";
import prunePlanFixture from "./fixtures/prune-plan.json";
import pressureFixture from "./fixtures/pressure.json";
import * as pressureApi from "@/lib/api/pressure";
import * as pruneApi from "@/lib/api/prune";
import * as backfillApi from "@/lib/api/backfill";

vi.mock("@/lib/api/pressure");
vi.mock("@/lib/api/prune");
vi.mock("@/lib/api/backfill");

function renderHygiene() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <HygienePage />
      <Toaster />
    </QueryClientProvider>
  );
}

describe("Prune flow (keystone)", () => {
  beforeEach(() => {
    // Set project scope so the Build plan button is enabled
    useProjectStore.setState({ project: "test-project" });
    // Freeze only Date (not setTimeout/setInterval) so waitFor and userEvent still work
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-04-10T12:00:00"));
    vi.clearAllMocks();
    vi.mocked(pressureApi.getPressure).mockResolvedValue(pressureFixture as Parameters<typeof pressureApi.getPressure>[0] extends never ? never : Awaited<ReturnType<typeof pressureApi.getPressure>>);
    vi.mocked(pruneApi.postPrunePlan).mockResolvedValue(prunePlanFixture as Awaited<ReturnType<typeof pruneApi.postPrunePlan>>);
    vi.mocked(pruneApi.postPruneApply).mockResolvedValue({
      plan_id: prunePlanFixture.plan_id,
      deleted: ["w1", "w2"],
      skipped: [],
    });
    vi.mocked(backfillApi.postBackfill).mockResolvedValue({
      dry_run: true,
      project: null,
      updated_by_tier: {},
      skipped: [],
      errors: [],
      total: 0,
    } as Awaited<ReturnType<typeof backfillApi.postBackfill>>);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test("build plan → type confirmation → dialog → apply → success toast", async () => {
    const user = userEvent.setup();
    renderHygiene();

    // Wait for pressure to load
    await waitFor(() => {
      expect(screen.getByText(/0\.12/)).toBeInTheDocument();
    });

    // Click "Build plan"
    await user.click(screen.getByRole("button", { name: /build plan/i }));

    // Wait for the plan review to appear
    await waitFor(() => {
      expect(screen.getByText(prunePlanFixture.plan_id)).toBeInTheDocument();
    });

    // Apply button exists but is disabled until typed id matches.
    // Use /apply.*delete/i to distinguish from BackfillRunner's "Apply" button.
    const applyInitial = screen.getByRole("button", { name: /apply.*delete/i });
    expect(applyInitial).toBeDisabled();

    // Type wrong id — stays disabled
    const input = screen.getByPlaceholderText(/…/);
    await user.type(input, "wrong");
    expect(screen.getByRole("button", { name: /apply.*delete/i })).toBeDisabled();

    // Clear and type correct
    await user.clear(input);
    await user.type(input, prunePlanFixture.plan_id);

    const primedApply = screen.getByRole("button", { name: /apply.*delete/i });
    expect(primedApply).toBeEnabled();

    // Click primed apply → dialog opens
    await user.click(primedApply);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    // Dialog title is "Delete 2 memories?" — check it exists (may match multiple nodes so query within dialog)
    expect(dialog.querySelector("h2")?.textContent).toMatch(/Delete 2 memories/i);

    // Confirm in the dialog — button text is "Delete 2 memories"
    await user.click(screen.getByRole("button", { name: /delete 2 memories/i }));

    // Apply was called with matching confirm
    await waitFor(() => {
      expect(pruneApi.postPruneApply).toHaveBeenCalledWith(prunePlanFixture.plan_id, prunePlanFixture.plan_id);
    });
  });

  test("apply is never called when typed id does not match", async () => {
    const user = userEvent.setup();
    renderHygiene();

    await waitFor(() => expect(screen.getByText(/0\.12/)).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /build plan/i }));
    await waitFor(() => expect(screen.getByText(prunePlanFixture.plan_id)).toBeInTheDocument());

    const input = screen.getByPlaceholderText(/…/);
    await user.type(input, "wrong");
    const apply = screen.getByRole("button", { name: /apply.*delete/i });
    expect(apply).toBeDisabled();

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(pruneApi.postPruneApply).not.toHaveBeenCalled();
  });
});
