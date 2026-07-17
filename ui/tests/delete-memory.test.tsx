import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { MemoryInspector } from "@/components/memory-inspector/memory-inspector";
import type { DetailResponseV2 } from "@/lib/schemas";

const detail: DetailResponseV2 = {
  memory: {
    memory_id: "2026-07-10_note_0ddba11",
    content: "Demo memory slated for deletion",
    type: "note",
    tier: "working",
    date: "2026-07-10",
    project: "net-lab",
  },
  neighbors: [],
  scope: { project: "net-lab", agent: "claude-code", repo_name: "net-lab" },
  relationships: [],
  storage: { qdrant: true, yaml: true },
  warnings: [],
};

const defaultProps = {
  open: true,
  detail,
  isLoading: false,
  currentProject: "net-lab",
  onClose: vi.fn(),
  onSelectMemory: vi.fn(),
};

function renderInspector(props = {}) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryInspector {...defaultProps} {...props} />
      <Toaster />
    </QueryClientProvider>
  );
  return client;
}

describe("guarded delete", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("delete button opens a confirm dialog naming the memory content", () => {
    renderInspector();

    fireEvent.click(screen.getByRole("button", { name: /delete memory/i }));

    expect(screen.getByText(/delete this memory\?/i)).toBeInTheDocument();
    // The preview names what is about to be destroyed.
    expect(
      screen.getAllByText(/demo memory slated for deletion/i).length
    ).toBeGreaterThan(1);
  });

  test("confirm fires DELETE with the UI mutation header and closes the inspector", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ deleted: true, memory_id: "2026-07-10_note_0ddba11" })
      )
    );
    vi.stubGlobal("fetch", fetchMock);
    const onClose = vi.fn();
    renderInspector({ onClose });

    fireEvent.click(screen.getByRole("button", { name: /delete memory/i }));
    fireEvent.click(screen.getByRole("button", { name: /confirm delete/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/memory/2026-07-10_note_0ddba11");
    expect(init.method).toBe("DELETE");
    expect((init.headers as Record<string, string>)["X-Rekall-UI"]).toBe("1");
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  test("cancel closes the dialog without any network call", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderInspector();

    fireEvent.click(screen.getByRole("button", { name: /delete memory/i }));
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

    await waitFor(() => {
      expect(screen.queryByText(/delete this memory\?/i)).not.toBeInTheDocument();
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("failed DELETE surfaces an error toast and keeps the inspector open", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "boom" }), { status: 500 })
    );
    vi.stubGlobal("fetch", fetchMock);
    const onClose = vi.fn();
    renderInspector({ onClose });

    fireEvent.click(screen.getByRole("button", { name: /delete memory/i }));
    fireEvent.click(screen.getByRole("button", { name: /confirm delete/i }));

    expect(await screen.findByText(/delete failed/i)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  test("successful delete invalidates the list caches", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ deleted: true, memory_id: "2026-07-10_note_0ddba11" })
      )
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = renderInspector();
    const invalidate = vi.spyOn(client, "invalidateQueries");

    fireEvent.click(screen.getByRole("button", { name: /delete memory/i }));
    fireEvent.click(screen.getByRole("button", { name: /confirm delete/i }));

    await waitFor(() => {
      const keys = invalidate.mock.calls.map(
        (c) => (c[0] as { queryKey: unknown[] }).queryKey[0]
      );
      expect(keys).toEqual(
        expect.arrayContaining(["brain-graph", "kb", "pressure", "resume", "search"])
      );
    });
  });

  test("edit affordance is present but disabled until U3", () => {
    renderInspector();
    const edit = screen.getByRole("button", { name: /edit \(coming in u3\)/i });
    expect(edit).toBeDisabled();
  });
});
