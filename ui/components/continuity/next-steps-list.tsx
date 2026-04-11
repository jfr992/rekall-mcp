import { SerifHeading } from "@/components/ui/serif-heading";
import { Empty } from "@/components/ui/empty";

export function NextStepsList({ steps }: { steps: unknown[] }) {
  if (steps.length === 0) {
    return <Empty title="No extracted next steps" />;
  }
  return (
    <section className="space-y-3">
      <SerifHeading title="Next Steps" size="section" eyebrow="WHAT TO DO NEXT" />
      <ul className="space-y-2">
        {steps.map((s, i) => (
          <li
            key={i}
            className="rounded-md border border-[var(--border)] bg-[var(--bg-elevated)] p-3 font-serif text-base text-[var(--fg)]"
          >
            {typeof s === "string" ? s : JSON.stringify(s)}
          </li>
        ))}
      </ul>
    </section>
  );
}
