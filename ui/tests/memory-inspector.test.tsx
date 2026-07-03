import { describe, test, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { MemoryInspector } from "@/components/memory-inspector/memory-inspector";
import type { DetailResponseV2 } from "@/lib/schemas";

// Inline fixture — mirrors detail-v2.json for stable types
const detail: DetailResponseV2 = {
  memory: {
    memory_id: "2026-07-01_decision_abc1",
    content: "Use PostgreSQL for primary store",
    type: "decision",
    tier: "working",
    durability: 0.65,
    reinforcement_count: 0,
    lifecycle_reason: "default for decision",
    date: "2026-07-01",
    project: "rekall-mcp",
    salience: 0.7,
  },
  neighbors: [
    {
      relation: "depends_on",
      memory: {
        memory_id: "2026-07-01_fact_bbb2",
        content: "Dependency fact",
        type: "fact",
        tier: "working",
        date: "2026-07-01",
        project: "rekall-mcp",
      },
    },
  ],
  scope: { project: "rekall-mcp", agent: "claude-code", repo_name: "rekall-mcp" },
  relationships: [
    {
      source_id: "2026-07-01_decision_aaa1",
      target_id: "2026-07-01_decision_abc1",
      neighbor_id: "2026-07-01_decision_aaa1",
      direction: "in",
      relation: "supersedes",
      weight: 0.8,
      auto: true,
      created: "2026-07-01",
      memory: {
        memory_id: "2026-07-01_decision_aaa1",
        content: "Superseder decision",
        type: "decision",
        project: "rekall-mcp",
        date: "2026-07-01",
      },
    },
    {
      source_id: "2026-07-01_decision_abc1",
      target_id: "2026-07-01_fact_bbb2",
      neighbor_id: "2026-07-01_fact_bbb2",
      direction: "out",
      relation: "depends_on",
      weight: 0.7,
      auto: true,
      created: "2026-07-01",
      memory: {
        memory_id: "2026-07-01_fact_bbb2",
        content: "Dependency fact",
        type: "fact",
        project: "rekall-mcp",
        date: "2026-07-01",
      },
    },
  ],
  provenance: {
    agent: "claude-code",
    source_tool: "save_memory",
    source_event: "PostToolUse",
    timestamp: "2026-07-01T10:00:00",
    session_id: "sess-xyz",
    repo_name: "rekall-mcp",
    repo_remote: "https://github.com/example/rekall-mcp",
    branch: "main",
    trust_boundary: "public",
  },
  lifecycle: {
    tier: "working",
    durability: 0.65,
    retention_days: 90,
    lifecycle_reason: "default for decision",
  },
  storage: { qdrant: true, yaml: false },
  warnings: [],
};

const defaultProps = {
  open: true,
  detail,
  isLoading: false,
  currentProject: "rekall-mcp",
  onClose: vi.fn(),
  onSelectMemory: vi.fn(),
};

describe("MemoryInspector", () => {
  test("title is 'Memory details'; content is not duplicated", () => {
    render(<MemoryInspector {...defaultProps} />);
    expect(screen.getByText("Memory details")).toBeInTheDocument();
    // Content should appear exactly once — not as a title, not twice
    const matches = screen.getAllByText("Use PostgreSQL for primary store");
    expect(matches).toHaveLength(1);
  });

  test("null durability renders 'unknown', not '0.00'", () => {
    const mod: DetailResponseV2 = {
      ...detail,
      lifecycle: { ...detail.lifecycle!, durability: null },
    };
    render(<MemoryInspector {...defaultProps} detail={mod} />);
    expect(screen.queryByText("0.00")).not.toBeInTheDocument();
    // "unknown" should appear at least for durability
    expect(screen.getAllByText("unknown").length).toBeGreaterThan(0);
  });

  test("actual durability 0 renders '0.00'", () => {
    const mod: DetailResponseV2 = {
      ...detail,
      lifecycle: { ...detail.lifecycle!, durability: 0 },
    };
    render(<MemoryInspector {...defaultProps} detail={mod} />);
    expect(screen.getByText("0.00")).toBeInTheDocument();
  });

  test("missing salience renders 'legacy/unknown', not a low numeric value", () => {
    const { salience: _removed, ...memWithoutSalience } = detail.memory!;
    const mod: DetailResponseV2 = { ...detail, memory: memWithoutSalience };
    render(<MemoryInspector {...defaultProps} detail={mod} />);
    expect(screen.getByText("legacy/unknown")).toBeInTheDocument();
  });

  test("provenance fields render in evidence rail", () => {
    render(<MemoryInspector {...defaultProps} />);
    expect(screen.getByText("claude-code")).toBeInTheDocument();
    expect(screen.getByText("save_memory")).toBeInTheDocument();
    expect(screen.getByText("main")).toBeInTheDocument();
    expect(screen.getByText("public")).toBeInTheDocument();
  });

  test("in-edge supersedes relation renders 'superseded by'", () => {
    render(<MemoryInspector {...defaultProps} />);
    expect(screen.getByText("superseded by")).toBeInTheDocument();
  });

  test("out-edge depends_on relation renders 'depends on'", () => {
    render(<MemoryInspector {...defaultProps} />);
    expect(screen.getByText("depends on")).toBeInTheDocument();
  });

  test("neighbor rows are buttons and call onSelectMemory with correct id", () => {
    const onSelectMemory = vi.fn();
    render(<MemoryInspector {...defaultProps} onSelectMemory={onSelectMemory} />);

    // Find the button containing the superseder neighbor content
    const supersederContent = screen.getByText("Superseder decision");
    const btn = supersederContent.closest("button");
    expect(btn).not.toBeNull();
    fireEvent.click(btn!);
    expect(onSelectMemory).toHaveBeenCalledWith("2026-07-01_decision_aaa1");
  });

  test("contradiction warning appears for in-edge contradicts relationship", () => {
    const contradictionDetail: DetailResponseV2 = {
      ...detail,
      relationships: [
        {
          source_id: "2026-07-01_decision_zzz9",
          target_id: detail.memory!.memory_id,
          neighbor_id: "2026-07-01_decision_zzz9",
          direction: "in",
          relation: "contradicts",
          weight: 0.9,
          auto: true,
          created: "2026-07-01",
          memory: {
            memory_id: "2026-07-01_decision_zzz9",
            content: "Earlier conflicting memory",
            type: "decision",
            project: "rekall-mcp",
          },
        },
      ],
    };
    render(<MemoryInspector {...defaultProps} detail={contradictionDetail} />);
    // Regex is specific to the warning banner text, not the relation label
    expect(screen.getByText(/contradicting relationships/i)).toBeInTheDocument();
  });

  test("contradiction warning appears for out-edge contradicts relationship", () => {
    const contradictionDetail: DetailResponseV2 = {
      ...detail,
      relationships: [
        {
          source_id: detail.memory!.memory_id,
          target_id: "2026-07-01_decision_zzz9",
          neighbor_id: "2026-07-01_decision_zzz9",
          direction: "out",
          relation: "contradicts",
          weight: 0.9,
          auto: true,
          created: "2026-07-01",
          memory: {
            memory_id: "2026-07-01_decision_zzz9",
            content: "Memory being contradicted",
            type: "decision",
            project: "rekall-mcp",
          },
        },
      ],
    };
    render(<MemoryInspector {...defaultProps} detail={contradictionDetail} />);
    expect(screen.getByText(/contradicting relationships/i)).toBeInTheDocument();
  });

  test("no contradiction warning when no contradicts relationships", () => {
    render(<MemoryInspector {...defaultProps} />);
    // Fixture has no contradicts relations — warning banner must not appear
    expect(screen.queryByText(/contradicting relationships/i)).not.toBeInTheDocument();
  });

  // --- CRITICAL: clipboard rejection fallback ---

  test("copyText: clipboard rejection shows copy-failed state with no unhandled rejection", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("Permission denied"));
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
      writable: true,
    });

    render(<MemoryInspector {...defaultProps} />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy memory ID" }));
    });

    // After rejection + failed execCommand (jsdom always returns false), button shows failed state
    expect(screen.getByRole("button", { name: "Copy failed" })).toBeInTheDocument();
  });

  // --- IMPORTANT: reinforcement_count in evidence rail ---

  test("reinforcement_count 3 renders '3×' in evidence rail", () => {
    const mod: DetailResponseV2 = {
      ...detail,
      memory: { ...detail.memory!, reinforcement_count: 3 },
    };
    render(<MemoryInspector {...defaultProps} detail={mod} />);
    expect(screen.getByText("3×")).toBeInTheDocument();
  });

  test("undefined reinforcement_count renders 'unknown' in evidence rail", () => {
    const { reinforcement_count: _removed, ...memWithout } = detail.memory!;
    const mod: DetailResponseV2 = { ...detail, memory: memWithout };
    render(<MemoryInspector {...defaultProps} detail={mod} />);
    // Durability is 0.65 (not null), so the only "unknown" comes from reinforcement
    expect(screen.getByText("unknown")).toBeInTheDocument();
  });

  // --- IMPORTANT: neighbor rows show date + project ---

  test("neighbor rows show date and project from relationship memory", () => {
    render(<MemoryInspector {...defaultProps} />);
    // Both relationship memories in fixture have date: "2026-07-01" and project: "rekall-mcp"
    // memory.project is also "rekall-mcp" but shown in the header; we assert multiple occurrences
    const projectLabels = screen.getAllByText("rekall-mcp");
    expect(projectLabels.length).toBeGreaterThan(1);
    // Dates: memory.date "2026-07-01" in header + at least one from relationship rows
    const dateLabels = screen.getAllByText("2026-07-01");
    expect(dateLabels.length).toBeGreaterThan(0);
  });

  // --- IMPORTANT: expand toggle ---

  test("expand toggle flips aria-expanded without triggering row navigation", () => {
    const onSelectMemory = vi.fn();
    render(<MemoryInspector {...defaultProps} onSelectMemory={onSelectMemory} />);

    const expandBtns = screen.getAllByRole("button", { name: "expand" });
    expect(expandBtns.length).toBeGreaterThan(0);

    const btn = expandBtns[0];
    expect(btn).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(btn);

    expect(btn).toHaveAttribute("aria-expanded", "true");
    expect(onSelectMemory).not.toHaveBeenCalled();
  });

  // --- Fix T9: deduped warnings ---

  test("warnings ['missing_provenance'] renders exactly one 'missing provenance' line", () => {
    const warnDetail: DetailResponseV2 = {
      ...detail,
      warnings: ["missing_provenance"],
      provenance: {
        agent: null,
        source_tool: null,
        source_event: null,
        timestamp: null,
        session_id: null,
        repo_name: null,
        repo_remote: null,
        branch: null,
        trust_boundary: null,
      },
    };
    render(<MemoryInspector {...defaultProps} detail={warnDetail} />);
    const items = screen.getAllByText("missing provenance");
    expect(items).toHaveLength(1);
  });

  // --- Fix T9: legacy source fallback ---

  test("all-null provenance renders 'no provenance recorded (legacy memory)'", () => {
    const legacyDetail: DetailResponseV2 = {
      ...detail,
      provenance: {
        agent: null,
        source_tool: null,
        source_event: null,
        timestamp: null,
        session_id: null,
        repo_name: null,
        repo_remote: null,
        branch: null,
        trust_boundary: null,
      },
    };
    render(<MemoryInspector {...defaultProps} detail={legacyDetail} />);
    expect(
      screen.getByText("no provenance recorded (legacy memory)"),
    ).toBeInTheDocument();
  });

  // --- IMPORTANT: status badge ---

  test("status badge shows 'superseded' when in-edge supersedes relationship present", () => {
    // Default fixture has relationships[0]: direction="in", relation="supersedes"
    render(<MemoryInspector {...defaultProps} />);
    expect(screen.getByText("superseded")).toBeInTheDocument();
  });

  // --- Fix 4: missing_neighbor_ids + null-memory relationship ---

  test("missing_neighbor_ids renders warning line with count and ids", () => {
    const detailWithMissing: DetailResponseV2 = {
      ...detail,
      relationships: [
        {
          source_id: "2026-07-01_decision_aaa1",
          target_id: detail.memory!.memory_id,
          neighbor_id: "2026-07-01_decision_aaa1",
          direction: "in" as const,
          relation: "supersedes",
          weight: 0.8,
          auto: true,
          created: "2026-07-01",
          memory: null,
        },
      ],
      missing_neighbor_ids: ["2026-07-01_decision_aaa1"],
    };
    render(<MemoryInspector {...defaultProps} detail={detailWithMissing} />);
    expect(screen.getByText(/graph edges point to 1 missing/i)).toBeInTheDocument();
  });

  test("null-memory relationship row renders 'memory unavailable' note", () => {
    const detailWithNullMem: DetailResponseV2 = {
      ...detail,
      relationships: [
        {
          source_id: "2026-07-01_decision_aaa1",
          target_id: detail.memory!.memory_id,
          neighbor_id: "2026-07-01_decision_aaa1",
          direction: "in" as const,
          relation: "supersedes",
          weight: 0.8,
          auto: true,
          created: "2026-07-01",
          memory: null,
        },
      ],
    };
    render(<MemoryInspector {...defaultProps} detail={detailWithNullMem} />);
    expect(screen.getByText("memory unavailable")).toBeInTheDocument();
  });

  test("status badge shows 'current' when no contradicts, no incoming supersedes, no legacy warnings", () => {
    const currentDetail: DetailResponseV2 = {
      ...detail,
      relationships: [
        {
          source_id: detail.memory!.memory_id,
          target_id: "2026-07-01_fact_bbb2",
          neighbor_id: "2026-07-01_fact_bbb2",
          direction: "out",
          relation: "depends_on",
          weight: 0.7,
          auto: true,
          created: "2026-07-01",
          memory: {
            memory_id: "2026-07-01_fact_bbb2",
            content: "Dependency fact",
            type: "fact",
            project: "rekall-mcp",
            date: "2026-07-01",
          },
        },
      ],
      warnings: [],
    };
    render(<MemoryInspector {...defaultProps} detail={currentDetail} />);
    expect(screen.getByText("current")).toBeInTheDocument();
  });
});
