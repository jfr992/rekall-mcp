import { Empty } from "@/components/ui/empty";

export function NextStepsList({ steps }: { steps: unknown[] }) {
  if (steps.length === 0) {
    return <Empty title="No extracted next steps" />;
  }
  return (
    <ul className="space-y-1.5">
      {steps.map((s, i) => (
        <li
          key={i}
          className="rounded-md border border-[var(--border)] bg-[var(--surface-0)] px-3 py-2 font-serif text-sm text-[var(--fg)]"
        >
          {typeof s === "string" ? s : JSON.stringify(s)}
        </li>
      ))}
    </ul>
  );
}
