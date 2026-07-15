import { describe, test, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { HealthBadge } from "@/components/shell/health-badge";
import { HealthSchema } from "@/lib/schemas";

const mockUseHealth = vi.fn();
vi.mock("@/lib/queries/use-health", () => ({
  useHealth: () => mockUseHealth(),
}));

describe("HealthBadge", () => {
  test("degraded status surfaces dead vector count", () => {
    mockUseHealth.mockReturnValue({
      data: { status: "degraded", vectors: { sampled: 256, zero_vectors: 12 } },
      isError: false,
      isLoading: false,
    });
    render(<HealthBadge />);
    expect(screen.getByText(/degraded · 12 dead vectors/i)).toBeInTheDocument();
  });

  test("degraded status surfaces embedder failure without fake vector count", () => {
    mockUseHealth.mockReturnValue({
      data: {
        status: "degraded",
        vectors: { sampled: 5, zero_vectors: 0 },
        embedder: { error: "ImportError: sentence-transformers required" },
      },
      isError: false,
      isLoading: false,
    });
    render(<HealthBadge />);
    expect(screen.getByText(/degraded · embedder down/i)).toBeInTheDocument();
    expect(screen.queryByText(/0 dead vectors/i)).not.toBeInTheDocument();
  });

  test("embedder failure tooltip carries the error detail", () => {
    mockUseHealth.mockReturnValue({
      data: {
        status: "degraded",
        vectors: { sampled: 5, zero_vectors: 0 },
        embedder: { error: "ImportError: sentence-transformers required" },
      },
      isError: false,
      isLoading: false,
    });
    const { container } = render(<HealthBadge />);
    expect(container.firstElementChild?.getAttribute("title")).toContain(
      "ImportError: sentence-transformers required"
    );
  });

  test("healthy status stays plain", () => {
    mockUseHealth.mockReturnValue({
      data: { status: "healthy", vectors: { sampled: 256, zero_vectors: 0 } },
      isError: false,
      isLoading: false,
    });
    render(<HealthBadge />);
    expect(screen.getByText(/^healthy$/i)).toBeInTheDocument();
  });
});

describe("HealthSchema", () => {
  test("accepts vectors block and legacy shape", () => {
    expect(() =>
      HealthSchema.parse({ status: "degraded", vectors: { sampled: 10, zero_vectors: 3 } })
    ).not.toThrow();
    expect(() => HealthSchema.parse({ status: "healthy" })).not.toThrow();
  });
});
