"use client";

import { useState } from "react";

const COLLAPSE_THRESHOLD = 500;

// ponytail: dumb string sniff on purpose — upgrade to a type-level flag if it misfires
export function looksLikeCommand(content: string): boolean {
  return (
    content.startsWith("Ran:") ||
    content.startsWith("$ ") ||
    content.includes("```")
  );
}

type Props = {
  content: string;
};

export function MemoryContent({ content }: Props) {
  const [expanded, setExpanded] = useState(false);
  const isLong = content.length > COLLAPSE_THRESHOLD;
  const displayContent =
    isLong && !expanded ? content.slice(0, COLLAPSE_THRESHOLD) + "…" : content;

  return (
    <div>
      {looksLikeCommand(content) ? (
        <pre
          className="whitespace-pre-wrap rounded-md bg-[var(--surface-1)] px-3 py-2.5 font-mono text-[13px] leading-relaxed text-[var(--fg)]"
          style={{ overflowWrap: "anywhere" }}
        >
          {displayContent}
        </pre>
      ) : (
        <p
          className="text-sm leading-relaxed text-[var(--fg)] whitespace-pre-wrap"
          style={{ overflowWrap: "anywhere" }}
        >
          {displayContent}
        </p>
      )}
      {isLong && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-2 text-xs text-[var(--accent-primary)] hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--accent-primary)]"
        >
          {expanded ? "Show less" : "Show full"}
        </button>
      )}
    </div>
  );
}
