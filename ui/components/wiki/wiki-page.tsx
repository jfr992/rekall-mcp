import type { ComponentPropsWithoutRef, ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { MonoLabel } from "@/components/ui/mono-label";
import { ValidityBadges } from "./validity-badge";
import type { WikiPage } from "@/lib/schemas";

const SOURCE_RE = /\[source: ([^\]\s]+)\]/g;
const ANCHOR_RE = /\s*\{#([\w-]+)\}\s*$/;

const linkSources = (body: string) =>
  body.replace(SOURCE_RE, (_, id: string) => `[source: ${id}](/brain?memory=${encodeURIComponent(id)})`);

function sectionHeading(Tag: "h2" | "h3" | "h4") {
  return function Heading({ children, node: _node, ...rest }: ComponentPropsWithoutRef<typeof Tag> & { node?: unknown }) {
    const text = typeof children === "string" ? children : null;
    const id = text?.match(ANCHOR_RE)?.[1];
    const shown: ReactNode = text && id ? text.replace(ANCHOR_RE, "") : children;
    return (
      <Tag id={id} className="mt-5 font-serif text-xl" {...rest}>
        {shown}
      </Tag>
    );
  };
}

const components = { h2: sectionHeading("h2"), h3: sectionHeading("h3"), h4: sectionHeading("h4") };

export function WikiPageView({ page }: { page: WikiPage }) {
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
        <nav aria-label="On this page" className="flex flex-wrap gap-3 text-sm">
          {page.sections.map((s) => (
            <a key={s} href={`#${s}`} className="text-[var(--accent-primary)] hover:underline">
              {s}
            </a>
          ))}
        </nav>
      ) : null}

      <div className="space-y-3 text-[15px] leading-relaxed text-[var(--fg)] [&_a]:text-[var(--accent-primary)] [&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:list-disc [&_ul]:pl-5">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {linkSources(page.body)}
        </ReactMarkdown>
      </div>
      {page.over_budget ? (
        <MonoLabel>truncated to budget (~{page.token_estimate} tokens)</MonoLabel>
      ) : null}
    </article>
  );
}
