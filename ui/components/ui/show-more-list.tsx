"use client";

import { Fragment, useState, type ReactNode } from "react";
import Link from "next/link";

type Props<T> = {
  items: T[];
  initialCount: number;
  renderItem: (item: T) => ReactNode;
  keyFor: (item: T, index: number) => string;
  viewAllHref?: string;
  moreLabel?: (remaining: number) => string;
  // Wraps the "show more"/"view all" control — pass `(node) => <li>{node}</li>`
  // when items render as <li> so the control stays valid inside a <ul>.
  footerWrapper?: (node: ReactNode) => ReactNode;
};

export function ShowMoreList<T>({
  items,
  initialCount,
  renderItem,
  keyFor,
  viewAllHref,
  moreLabel,
  footerWrapper = (node) => node,
}: Props<T>) {
  const [expanded, setExpanded] = useState(false);
  const hasMore = items.length > initialCount;
  const shown = expanded || !hasMore ? items : items.slice(0, initialCount);
  const remaining = items.length - initialCount;
  const label = moreLabel
    ? moreLabel(remaining)
    : viewAllHref
      ? `View all ${items.length} →`
      : `Show ${remaining} more`;

  return (
    <>
      {shown.map((item, i) => (
        <Fragment key={keyFor(item, i)}>{renderItem(item)}</Fragment>
      ))}
      {hasMore
        ? footerWrapper(
            viewAllHref ? (
              <Link href={viewAllHref}>{label}</Link>
            ) : !expanded ? (
              <button type="button" onClick={() => setExpanded(true)}>
                {label}
              </button>
            ) : null
          )
        : null}
    </>
  );
}
