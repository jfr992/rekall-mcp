import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import SessionsPage from "@/app/sessions/page";
import sessionsFixture from "./fixtures/sessions.json";
import sessionDetailFixture from "./fixtures/session-detail.json";
import unattributedDetailFixture from "./fixtures/session-detail-unattributed.json";
import detailV2Fixture from "./fixtures/detail-v2.json";
import * as sessionsApi from "@/lib/api/sessions";
import * as feedbackApi from "@/lib/api/feedback";
import * as detailApi from "@/lib/api/detail";
import { useProjectStore } from "@/lib/project-store";
import type { SessionDetail, SessionsResponse } from "@/lib/schemas";

vi.mock("@/lib/api/sessions");
vi.mock("@/lib/api/feedback");
vi.mock("@/lib/api/detail");

function renderSessions() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <SessionsPage />
      <Toaster />
    </QueryClientProvider>
  );
}

describe("Sessions surface", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useProjectStore.setState({ project: "" });
    vi.mocked(sessionsApi.getSessions).mockResolvedValue(
      sessionsFixture as SessionsResponse
    );
    vi.mocked(sessionsApi.getSessionDetail).mockImplementation((id: string) =>
      Promise.resolve(
        (id === "sess-abc123"
          ? sessionDetailFixture
          : unattributedDetailFixture) as SessionDetail
      )
    );
  });

  test("list renders session rows with totals from fixture", async () => {
    renderSessions();
    await waitFor(() => {
      expect(screen.getByText(/sess-abc123/)).toBeInTheDocument();
    });
    expect(screen.getByText(/2 recalls/i)).toBeInTheDocument();
    expect(screen.getByText(/3 injected/i)).toBeInTheDocument();
    expect(screen.getByText(/1450 tok/i)).toBeInTheDocument();
  });

  test("sidebar scope filters the list to the selected project", async () => {
    useProjectStore.setState({ project: "byte-edge" });
    // Backend contract: ?project= returns only that project's sessions.
    vi.mocked(sessionsApi.getSessions).mockImplementation((project) => {
      const all = (sessionsFixture as SessionsResponse).sessions;
      return Promise.resolve({
        sessions: project ? all.filter((s) => s.project === project) : all,
        window: 5000,
      });
    });
    renderSessions();

    await waitFor(() => {
      expect(screen.getByText(/sess-be-777/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/sess-abc123/)).not.toBeInTheDocument();
    expect(screen.queryByText(/unattributed · rekall-mcp/i)).not.toBeInTheDocument();
    expect(sessionsApi.getSessions).toHaveBeenCalledWith("byte-edge", 50);
  });

  test("clicking a session shows recall cards with scores", async () => {
    const user = userEvent.setup();
    renderSessions();
    await user.click(await screen.findByText(/sess-abc123/));

    expect(
      await screen.findByText(/vector corruption tripwire/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/0\.91/)).toBeInTheDocument();
    expect(screen.getByText(/0\.84/)).toBeInTheDocument();
    expect(sessionsApi.getSessionDetail).toHaveBeenCalledWith("sess-abc123");
  });

  test("feedback click posts the verdict for that memory", async () => {
    vi.mocked(feedbackApi.postFeedback).mockResolvedValue({ recorded: true });
    const user = userEvent.setup();
    renderSessions();
    await user.click(await screen.findByText(/sess-abc123/));
    await screen.findByText(/vector corruption tripwire/i);

    const [useful] = screen.getAllByRole("button", {
      name: /mark 2026-07-10_decision_a1b2c3 useful/i,
    });
    await user.click(useful);

    await waitFor(() => {
      expect(feedbackApi.postFeedback).toHaveBeenCalledWith(
        "2026-07-10_decision_a1b2c3",
        "useful",
        "sess-abc123"
      );
    });
  });

  test("failed feedback POST reverts optimistic state and surfaces an error", async () => {
    let rejectPost!: (e: Error) => void;
    vi.mocked(feedbackApi.postFeedback).mockImplementation(
      () =>
        new Promise((_resolve, reject) => {
          rejectPost = reject;
        })
    );
    const user = userEvent.setup();
    renderSessions();
    await user.click(await screen.findByText(/sess-abc123/));
    await screen.findByText(/vector corruption tripwire/i);

    const [useful] = screen.getAllByRole("button", {
      name: /mark 2026-07-10_decision_a1b2c3 useful/i,
    });
    await user.click(useful);
    // Optimistic: verdict is marked before the POST settles.
    expect(useful).toHaveAttribute("aria-pressed", "true");

    act(() => rejectPost(new Error("backend down")));

    await waitFor(() => {
      expect(useful).toHaveAttribute("aria-pressed", "false");
    });
    expect(await screen.findByText(/feedback failed/i)).toBeInTheDocument();
  });

  test("unattributed session shows an explanatory caption", async () => {
    const user = userEvent.setup();
    renderSessions();
    await user.click(await screen.findByText(/unattributed · rekall-mcp/i));

    expect(
      await screen.findByText(/couldn't be attributed to a specific session/i)
    ).toBeInTheDocument();
    expect(sessionsApi.getSessionDetail).toHaveBeenCalledWith(
      "unattributed:rekall-mcp"
    );
  });

  test("detail lists injected memories, null token estimates render as —", async () => {
    const user = userEvent.setup();
    renderSessions();
    await user.click(await screen.findByText(/sess-abc123/));
    await screen.findByText(/vector corruption tripwire/i);

    expect(screen.getByText(/injected \(3\)/i)).toBeInTheDocument();
    // All three injected rows carry null token_estimate in the fixture.
    expect(screen.getAllByText("—")).toHaveLength(3);
  });

  test("clicking a memory id expands it in the inspector", async () => {
    vi.mocked(detailApi.getMemoryDetail).mockResolvedValue(
      detailV2Fixture as Awaited<ReturnType<typeof detailApi.getMemoryDetail>>
    );
    const user = userEvent.setup();
    renderSessions();
    await user.click(await screen.findByText(/sess-abc123/));
    await screen.findByText(/vector corruption tripwire/i);

    const [memoryButton] = screen.getAllByRole("button", {
      name: /expand 2026-07-10_decision_a1b2c3/i,
    });
    await user.click(memoryButton);

    await waitFor(() => {
      expect(detailApi.getMemoryDetail).toHaveBeenCalledWith(
        "2026-07-10_decision_a1b2c3",
        undefined
      );
    });
    expect(
      await screen.findByText(/use postgresql for primary store/i)
    ).toBeInTheDocument();
  });
});
