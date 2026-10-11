import { describe, expect, test, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { BackfillRunner } from "@/components/hygiene/backfill-runner";

const report = {
  dry_run: true, project: null, updated_by_tier: { working: 3 }, skipped: [], errors: [], total: 3,
  tier_changes: { promoted: 2, demoted: 1, unchanged: 0 },
  changed: [{ memory_id: "m1", from: "working", to: "episodic" }],
};

function setup(project?: string) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(report))));
  const ui = (p?: string) => (
    <QueryClientProvider client={client}>
      <BackfillRunner project={p} />
      <Toaster />
    </QueryClientProvider>
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(ui(project));
  return { view, ui };
}

describe("BackfillRunner", () => {
  test("dry run lists what will move; Apply confirms with that count", async () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: /dry run/i }));
    expect(await screen.findAllByText(/2 promoted · 1 demoted/)).not.toHaveLength(0);
    expect(screen.getByText(/m1: working → episodic/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('{"working"');
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));
    expect(confirm).toHaveBeenCalledWith(expect.stringMatching(/1 memor/));
  });

  test("changing project disarms Apply", async () => {
    const { view, ui } = setup("a");
    fireEvent.click(screen.getByRole("button", { name: /dry run/i }));
    await screen.findAllByText(/2 promoted · 1 demoted/);
    expect(screen.getByRole("button", { name: /apply/i })).toBeEnabled();
    view.rerender(ui("b"));
    expect(screen.getByRole("button", { name: /apply/i })).toBeDisabled();
  });
});
