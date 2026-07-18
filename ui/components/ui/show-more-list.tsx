"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";

type Props<T> = {
  items: T[];
  initialCount: number;
  renderItem: (item: T) => ReactNode;
  keyFor: (item: T) => string;
  viewAllHref?: string;
  moreLabel?: (remaining: number) => string;
};

export function ShowMoreList<T>({
  items,
  initialCount,
  renderItem,
  keyFor,
  viewAllHref,
  moreLabel = (n) => `Show ${n} more`,
}: Props<T>) {
  const [expanded, setExpanded] = useState(false);
  const hasMore = items.length > initialCount;
  const shown = expanded || !hasMore ? items : items.slice(0, initialCount);
  const remaining = items.length - initialCount;

  return (
    <>
      {shown.map((item) => (
        <div key={keyFor(item)}>{renderItem(item)}</div>
      ))}
      {hasMore && viewAllHref ? (
        <Link href={viewAllHref}>View all {items.length} →</Link>
      ) : hasMore && !expanded ? (
        <button type="button" onClick={() => setExpanded(true)}>
          {moreLabel(remaining)}
        </button>
      ) : null}
    </>
  );
}
