import type { ComponentPropsWithoutRef, ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { MonoLabel } from "@/components/ui/mono-label";
import { ValidityBadges } from "./validity-badge";
import type { WikiPage } from "@/lib/schemas";

const SOURCE_RE = /\[source:\s*([^\]]+)\]/g;
const ANCHOR_RE = /\s*\{#([\w-]+)\}\s*$/;
const SOURCE_HREF = "#source:";

type MdNode = { type: string; value?: string; url?: string; children?: MdNode[] };

function splitSources(value: string): MdNode[] {
  const out: MdNode[] = [];
  let last = 0;
  for (const m of value.matchAll(SOURCE_RE)) {
    const ids = m[1].split(",").map((s) => s.trim()).filter(Boolean);
    if (!ids.length) continue;
    out.push({ type: "text", value: value.slice(last, m.index) + "[source: " });
    ids.forEach((id, i) => {
      if (i) out.push({ type: "text", value: ", " });
      out.push({ type: "link", url: SOURCE_HREF + encodeURIComponent(id), children: [{ type: "text", value: id }] });
    });
    out.push({ type: "text", value: "]" });
    last = (m.index ?? 0) + m[0].length;
  }
  if (!out.length) return [{ type: "text", value }];
  out.push({ type: "text", value: value.slice(last) });
  return out;
}

// Only `text` nodes are rewritten; code and inlineCode nodes carry `value` and are left alone.
function rewriteSources(node: MdNode): void {
  if (!node.children) return;
  node.children = node.children.flatMap((c) => {
    if (c.type === "text" && c.value) return splitSources(c.value);
    rewriteSources(c);
    return [c];
  });
}

const remarkSourceLinks = () => (tree: MdNode) => rewriteSources(tree);

function flattenText(node: ReactNode): string | null {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) {
    const parts = node.map(flattenText);
    return parts.every((p) => p !== null) ? parts.join("") : null;
  }
  return null;
}

type HeadingProps<T extends "h1" | "h2" | "h3" | "h4"> = ComponentPropsWithoutRef<T> & { node?: unknown };

function sectionHeading<T extends "h1" | "h2" | "h3" | "h4">(Tag: T) {
  return function Heading({ children, node, ...rest }: HeadingProps<T>) {
    void node;
    const text = flattenText(children);
    const id = text?.match(ANCHOR_RE)?.[1];
    const El = Tag as "h2";
    return (
      <El id={id} className="mt-5 font-serif text-xl" {...(rest as object)}>
        {text !== null && id ? text.replace(ANCHOR_RE, "") : children}
      </El>
    );
  };
}

type Props = {
  page: WikiPage;
  onOpenSource?: (memoryId: string) => void;
  onOpenSection?: (sectionId: string) => void;
  full?: boolean;
  onToggleFull?: () => void;
};

export function WikiPageView({ page, onOpenSource, onOpenSection, full = false, onToggleFull }: Props) {
  const components = {
    h1: sectionHeading("h1"),
    h2: sectionHeading("h2"),
    h3: sectionHeading("h3"),
    h4: sectionHeading("h4"),
    a: ({ href, children, node, ...rest }: ComponentPropsWithoutRef<"a"> & { node?: unknown }) => {
      void node;
      if (href?.startsWith(SOURCE_HREF)) {
        const id = decodeURIComponent(href.slice(SOURCE_HREF.length));
        return (
          <a
            href={href}
            onClick={(e) => {
              e.preventDefault();
              onOpenSource?.(id);
            }}
          >
            {children}
          </a>
        );
      }
      return (
        <a href={href} target="_blank" rel="noreferrer" {...rest}>
          {children}
        </a>
      );
    },
  };

  return (
    <article className="flex min-w-0 flex-col gap-4">
      <header className="flex flex-col gap-1.5">
        <div className="flex items-center gap-3">
          <h1 className="font-serif text-3xl">{page.title ?? page.page_id}</h1>
          <ValidityBadges validity={page.validity} status={page.status} />
        </div>
        <MonoLabel className="break-all">
          {page.page_id} · rev {page.revision ?? "—"} · {page.type}
          {page.scope ? ` · ${JSON.stringify(page.scope)}` : ""} · verified {page.last_verified ?? "never"}
        </MonoLabel>
      </header>

      {page.validity !== "ok" ? (
        <div role="alert" className="rounded-[var(--radius-lg)] border border-amber-400/40 p-3 text-sm">
          <strong className="uppercase">{page.validity}</strong>
          {page.validity_reasons.length ? `: ${page.validity_reasons.join("; ")}` : null}
        </div>
      ) : null}

      {page.sections.length ? (
        <nav aria-label="On this page" className="flex flex-wrap items-center gap-3 text-sm">
          {page.sections.map((s) => (
            <button
              key={s}
              type="button"
              aria-current={page.section_id === s ? "true" : undefined}
              onClick={() => onOpenSection?.(s)}
              className={`cursor-pointer hover:underline ${
                page.section_id === s ? "text-[var(--fg)]" : "text-[var(--accent-primary)]"
              }`}
            >
              {s}
            </button>
          ))}
          <button
            type="button"
            aria-pressed={full}
            onClick={() => onToggleFull?.()}
            className="ml-auto cursor-pointer rounded-[7px] border border-[var(--border)] px-2 py-0.5 text-xs text-[var(--fg-dim)] hover:text-[var(--fg)]"
          >
            Full page
          </button>
        </nav>
      ) : null}

      <div className="space-y-3 text-[15px] leading-relaxed text-[var(--fg)] [&_a]:cursor-pointer [&_a]:text-[var(--accent-primary)] [&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:list-disc [&_ul]:pl-5">
        <ReactMarkdown remarkPlugins={[remarkGfm, remarkSourceLinks]} components={components}>
          {page.body}
        </ReactMarkdown>
      </div>
      {page.over_budget ? <MonoLabel>truncated to budget (~{page.token_estimate} tokens)</MonoLabel> : null}
    </article>
  );
}
