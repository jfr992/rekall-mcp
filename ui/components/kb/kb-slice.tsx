import { KbEntry } from "./kb-entry";
import { KbEmpty } from "./kb-empty";
import { MonoLabel } from "@/components/ui/mono-label";
import type { KbEntry as KbEntryType } from "@/lib/schemas";

type Props = {
  title: string;
  accentVar: string;
  entries: KbEntryType[];
};

export function KbSlice({ title, accentVar, entries }: Props) {
  return (
    <section
      className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-elevated)]"
      style={{ borderLeft: `3px solid ${accentVar}` }}
    >
      <header className="flex shrink-0 items-baseline justify-between gap-3 border-b border-[var(--border)] px-5 py-4">
        <h2 className="font-serif text-xl">{title}</h2>
        <MonoLabel>{entries.length}</MonoLabel>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-4">
        {entries.length === 0 ? (
          <KbEmpty label={title.toLowerCase()} />
        ) : (
          <ul>
            {entries.map((e, i) => (
              <KbEntry key={e.memory_id ?? `${e.summary}-${i}`} entry={e} />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
