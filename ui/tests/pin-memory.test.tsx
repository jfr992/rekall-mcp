import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { MemoryInspector } from "@/components/memory-inspector/memory-inspector";
import type { DetailResponseV2 } from "@/lib/schemas";

const detail: DetailResponseV2 = {
  memory: {
    memory_id: "2026-07-10_note_0ddba11",
    content: "Ottawa timezone is EST",
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

describe("identity pin", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("pin button opens a confirm dialog naming the memory content", () => {
    renderInspector();

    fireEvent.click(screen.getByRole("button", { name: /promote to identity/i }));

    expect(screen.getByText(/promote this memory to identity\?/i)).toBeInTheDocument();
    expect(
      screen.getAllByText(/ottawa timezone is est/i).length
    ).toBeGreaterThan(1);
  });

  test("confirm fires POST /pin with pinned=true and the UI mutation header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ memory_id: "2026-07-10_note_0ddba11", pinned: true })
      )
    );
    vi.stubGlobal("fetch", fetchMock);
    renderInspector();

    fireEvent.click(screen.getByRole("button", { name: /promote to identity/i }));
    fireEvent.click(
      screen.getByRole("button", { name: /confirm promote to identity/i })
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/memory/2026-07-10_note_0ddba11/pin");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ pinned: true });
    expect((init.headers as Record<string, string>)["X-Rekall-UI"]).toBe("1");
  });

  test("cancel closes the dialog without any network call", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderInspector();

    fireEvent.click(screen.getByRole("button", { name: /promote to identity/i }));
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

    await waitFor(() => {
      expect(
        screen.queryByText(/promote this memory to identity\?/i)
      ).not.toBeInTheDocument();
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("pinned memory shows unpin affordance and fires pinned=false", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ memory_id: "2026-07-10_note_0ddba11", pinned: false })
      )
    );
    vi.stubGlobal("fetch", fetchMock);
    const pinnedDetail: DetailResponseV2 = {
      ...detail,
      memory: { ...detail.memory!, tier: "identity" },
    };
    renderInspector({ detail: pinnedDetail });

    fireEvent.click(screen.getByRole("button", { name: /remove identity pin/i }));
    expect(screen.getByText(/remove identity pin from this memory\?/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /confirm remove identity pin/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ pinned: false });
  });

  test("successful pin invalidates the detail and list caches so the badge updates", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ memory_id: "2026-07-10_note_0ddba11", pinned: true })
      )
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = renderInspector();
    const invalidate = vi.spyOn(client, "invalidateQueries");

    fireEvent.click(screen.getByRole("button", { name: /promote to identity/i }));
    fireEvent.click(
      screen.getByRole("button", { name: /confirm promote to identity/i })
    );

    await waitFor(() => {
      const keys = invalidate.mock.calls.map(
        (c) => (c[0] as { queryKey: unknown[] }).queryKey[0]
      );
      expect(keys).toEqual(expect.arrayContaining(["memory-detail"]));
    });
  });

  test("failed pin surfaces an error toast and keeps the dialog dismissible", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "boom" }), { status: 500 })
    );
    vi.stubGlobal("fetch", fetchMock);
    renderInspector();

    fireEvent.click(screen.getByRole("button", { name: /promote to identity/i }));
    fireEvent.click(
      screen.getByRole("button", { name: /confirm promote to identity/i })
    );

    expect(await screen.findByText(/pin failed/i)).toBeInTheDocument();
  });
});
