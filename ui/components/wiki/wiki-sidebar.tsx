import { MonoLabel } from "@/components/ui/mono-label";
import { ValidityBadges } from "./validity-badge";
import type { WikiIndexEntry } from "@/lib/schemas";

type Props = {
  entries: WikiIndexEntry[];
  selected: string | null;
  onSelect: (pageId: string) => void;
};

function groupEntries(entries: WikiIndexEntry[]): [string, WikiIndexEntry[]][] {
  const groups = new Map<string, WikiIndexEntry[]>();
  for (const e of entries) {
    const key = `${e.project} / ${e.type}`;
    groups.set(key, [...(groups.get(key) ?? []), e]);
  }
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
}

export function WikiSidebar({ entries, selected, onSelect }: Props) {
  return (
    <nav aria-label="Wiki pages" className="flex flex-col gap-4">
      {groupEntries(entries).map(([group, items]) => (
        <section key={group}>
          <MonoLabel className="mb-1 block">{group}</MonoLabel>
          <ul>
            {items.map((e) => (
              <li key={e.page_id}>
                <button
                  type="button"
                  aria-current={selected === e.page_id ? "page" : undefined}
                  onClick={() => onSelect(e.page_id)}
                  className={`flex w-full cursor-pointer items-center justify-between gap-2 rounded-[7px] px-2 py-1.5 text-left text-sm transition-colors hover:bg-[var(--surface-0)] ${
                    selected === e.page_id ? "bg-[rgba(45,212,160,0.14)] text-[var(--fg)]" : "text-[var(--fg)]"
                  }`}
                >
                  <span className="min-w-0 truncate">{e.title ?? e.page_id}</span>
                  <ValidityBadges validity={e.validity} status={e.status} />
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </nav>
  );
}
