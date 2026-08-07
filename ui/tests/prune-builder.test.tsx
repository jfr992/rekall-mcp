import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { PruneBuilder } from "@/components/hygiene/prune-builder";

describe("PruneBuilder", () => {
  it("disables the button and shows the hint when no project scope", () => {
    render(
      <PruneBuilder
        onBuild={vi.fn()}
        loading={false}
        disabled
        hint="Select a project scope to build a prune plan"
      />
    );
    expect(screen.getByRole("button", { name: /build plan/i })).toBeDisabled();
    expect(screen.getByText(/select a project scope/i)).toBeInTheDocument();
  });

  it("stays clickable with a project scope and hides the hint", () => {
    const onBuild = vi.fn();
    render(<PruneBuilder onBuild={onBuild} loading={false} hint="unused" />);
    expect(screen.queryByText(/unused/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /build plan/i }));
    expect(onBuild).toHaveBeenCalledOnce();
  });
});
