import { SerifHeading } from "@/components/ui/serif-heading";
import { MonoLabel } from "@/components/ui/mono-label";
import { Empty } from "@/components/ui/empty";

type RecentItem = {
  memory_id: string;
  content: string;
  date?: string;
  type?: string;
};

export function RecentSection({ items }: { items: RecentItem[] }) {
  return (
    <section className="space-y-3">
      <SerifHeading title="Recent" size="section" eyebrow="MOST RECENT BY DATE" />
      {items.length === 0 ? (
        <Empty title="No recent activity" />
      ) : (
        <ol className="relative space-y-4 border-l border-[var(--border)] pl-4">
          {items.map((item) => (
            <li key={item.memory_id} className="relative">
              <span
                className="absolute -left-[22px] top-1.5 h-2 w-2 rounded-full bg-[var(--accent-primary)]"
                style={{ boxShadow: "0 0 8px var(--accent-primary)" }}
              />
              <MonoLabel>{item.date ?? ""}</MonoLabel>
              <p className="mt-1 text-sm text-[var(--fg)]">{item.content}</p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
