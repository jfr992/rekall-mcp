import { useState } from "react";
import { MonoLabel } from "@/components/ui/mono-label";
import { ValidityBadges } from "./validity-badge";
import { useWikiSearch } from "@/lib/queries/use-wiki";

type Props = { project: string; onOpen: (pageId: string, sectionId: string | null) => void };

export function WikiSearch({ project, onOpen }: Props) {
  const [q, setQ] = useState("");
  const { data, isError } = useWikiSearch(q, project);
  return (
    <div className="flex flex-col gap-3">
      <input
        type="search"
        aria-label="Search wiki"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search the wiki"
        className="w-full rounded-[7px] border border-[var(--border)] bg-transparent px-3 py-1.5 text-sm text-[var(--fg)]"
      />
      {isError ? <p className="text-sm text-red-400">Search failed</p> : null}
      {data && data.hits.length === 0 ? <p className="text-sm text-[var(--fg-dim)]">No hits.</p> : null}
      <ul className="space-y-2">
        {data?.hits.map((h) => (
          <li key={`${h.page_id}#${h.section_id}`}>
            <button
              type="button"
              onClick={() => onOpen(h.page_id, h.section_id)}
              className="w-full cursor-pointer rounded-[var(--radius-lg)] border border-[var(--border)] p-3 text-left hover:bg-[var(--surface-0)]"
            >
              <span className="flex items-center justify-between gap-2">
                <span className="truncate text-sm text-[var(--fg)]">{h.title ?? h.page_id}</span>
                <ValidityBadges validity={h.validity} status={h.status} />
              </span>
              {h.section_id ? <MonoLabel className="block">§ {h.section_id}</MonoLabel> : null}
              <p className="mt-1 line-clamp-3 text-xs text-[var(--fg-dim)]">{h.excerpt}</p>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
