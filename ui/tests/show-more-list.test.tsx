import { describe, test, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ShowMoreList } from "@/components/ui/show-more-list";

type Item = { id: string; label: string };

function items(n: number): Item[] {
  return Array.from({ length: n }, (_, i) => ({ id: `i${i}`, label: `Item ${i}` }));
}

describe("ShowMoreList", () => {
  test("renders only initialCount items when total exceeds it", () => {
    render(
      <ShowMoreList
        items={items(15)}
        initialCount={5}
        renderItem={(item) => <span>{item.label}</span>}
        keyFor={(item) => item.id}
      />
    );
    expect(screen.getByText("Item 0")).toBeInTheDocument();
    expect(screen.getByText("Item 4")).toBeInTheDocument();
    expect(screen.queryByText("Item 5")).not.toBeInTheDocument();
    expect(screen.queryByText("Item 14")).not.toBeInTheDocument();
  });

  test('shows a "Show N more" button with the correct remaining count', () => {
    render(
      <ShowMoreList
        items={items(15)}
        initialCount={5}
        renderItem={(item) => <span>{item.label}</span>}
        keyFor={(item) => item.id}
      />
    );
    expect(
      screen.getByRole("button", { name: "Show 10 more" })
    ).toBeInTheDocument();
  });

  test("clicking Show more reveals the rest in a single step, then removes the button", () => {
    render(
      <ShowMoreList
        items={items(15)}
        initialCount={5}
        renderItem={(item) => <span>{item.label}</span>}
        keyFor={(item) => item.id}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Show 10 more" }));

    expect(screen.getByText("Item 14")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /show \d+ more/i })
    ).not.toBeInTheDocument();
  });

  test("no expander when items fit within initialCount", () => {
    render(
      <ShowMoreList
        items={items(3)}
        initialCount={5}
        renderItem={(item) => <span>{item.label}</span>}
        keyFor={(item) => item.id}
      />
    );
    expect(screen.getByText("Item 0")).toBeInTheDocument();
    expect(screen.getByText("Item 2")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /show \d+ more/i })
    ).not.toBeInTheDocument();
  });

  test("href mode renders a View all N link instead of expanding", () => {
    render(
      <ShowMoreList
        items={items(15)}
        initialCount={5}
        renderItem={(item) => <span>{item.label}</span>}
        keyFor={(item) => item.id}
        viewAllHref="/stream"
      />
    );
    const link = screen.getByRole("link", { name: "View all 15 →" });
    expect(link).toHaveAttribute("href", "/stream");
    expect(
      screen.queryByRole("button", { name: /show \d+ more/i })
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Item 14")).not.toBeInTheDocument();
  });

  test("href mode renders no link when items fit within initialCount", () => {
    render(
      <ShowMoreList
        items={items(3)}
        initialCount={5}
        renderItem={(item) => <span>{item.label}</span>}
        keyFor={(item) => item.id}
        viewAllHref="/stream"
      />
    );
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  test("accepts an optional custom label prefix", () => {
    render(
      <ShowMoreList
        items={items(15)}
        initialCount={5}
        renderItem={(item) => <span>{item.label}</span>}
        keyFor={(item) => item.id}
        moreLabel={(n) => `Show all ${n} more from today`}
      />
    );
    expect(
      screen.getByRole("button", { name: "Show all 10 more from today" })
    ).toBeInTheDocument();
  });
});
