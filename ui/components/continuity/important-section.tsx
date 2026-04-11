import { SerifHeading } from "@/components/ui/serif-heading";
import { Badge } from "@/components/ui/badge";
import { MonoLabel } from "@/components/ui/mono-label";
import { Empty } from "@/components/ui/empty";

type ImportantItem = {
  memory_id: string;
  content: string;
  type?: string;
  tier?: string;
  date?: string;
  importance?: number;
};

export function ImportantSection({ items }: { items: ImportantItem[] }) {
  return (
    <section className="space-y-3">
      <SerifHeading title="Important" size="section" eyebrow="HIGH-SIGNAL MEMORIES" />
      {items.length === 0 ? (
        <Empty title="Nothing important yet" />
      ) : (
        <ul className="space-y-2">
          {items.map((item) => (
            <li
              key={item.memory_id}
              className="rounded-md border border-[var(--border)] bg-[var(--bg-elevated)] p-4"
            >
              <div className="mb-2 flex items-center gap-2">
                {item.type ? <Badge kind="type" value={item.type} /> : null}
                {item.tier ? <Badge kind="tier" value={item.tier} /> : null}
                <MonoLabel>{item.date ?? ""}</MonoLabel>
              </div>
              <p className="font-serif text-base leading-snug text-[var(--fg)]">{item.content}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
