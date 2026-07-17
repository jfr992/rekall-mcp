import { MonoLabel } from "@/components/ui/mono-label";
import { Card } from "@/components/ui/card";

type Props = {
  scope: Record<string, unknown> | null;
};

const FIELDS: Array<[string, string]> = [
  ["project", "project"],
  ["agent", "agent"],
  ["repo_name", "repo"],
  ["branch", "branch"],
  ["trust_boundary", "trust"],
];

export function ResumeHeader({ scope }: Props) {
  if (!scope) return null;
  return (
    <Card variant="glass">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
        {FIELDS.map(([key, label]) => {
          const value = scope[key];
          if (!value) return null;
          return (
            <div key={key}>
              <MonoLabel className="tracking-[0.16em]">{label}</MonoLabel>
              <div className="mt-1 font-mono text-sm text-[var(--fg)]">{String(value)}</div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
