import { describe, test, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { WikiSidebar } from "@/components/wiki/wiki-sidebar";
import fixture from "./fixtures/wiki-index.json";
import { WikiIndexSchema } from "@/lib/schemas";

describe("WikiSidebar", () => {
  test("groups by project and type and shows validity badges", () => {
    const data = WikiIndexSchema.parse(fixture);
    render(<WikiSidebar entries={data.entries} selected={null} onSelect={() => {}} />);
    expect(screen.getByText(/demo \/ process/i)).toBeInTheDocument();
    expect(screen.getByText(/demo \/ policy/i)).toBeInTheDocument();
    expect(screen.getByText(/stale/i)).toBeInTheDocument();
  });

  test("selecting an entry calls onSelect with the page id", () => {
    const data = WikiIndexSchema.parse(fixture);
    const onSelect = vi.fn();
    render(<WikiSidebar entries={data.entries} selected={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByText(/rotate gateway key/i));
    expect(onSelect).toHaveBeenCalledWith("demo/process/rotate-key");
  });
});
