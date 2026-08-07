"use client";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { SerifHeading } from "@/components/ui/serif-heading";
import { MonoLabel } from "@/components/ui/mono-label";

type Props = {
  onBuild: () => void;
  loading: boolean;
  disabled?: boolean;
  hint?: string;
};

export function PruneBuilder({ onBuild, loading, disabled, hint }: Props) {
  return (
    <Card variant="flat" className="flex h-full flex-col">
      <SerifHeading title="Build a prune plan" size="section" eyebrow="DRY RUN" />
      <p className="mt-1.5 text-sm text-[var(--fg-muted)]">
        Selects up to 200 candidates. Identity tier and memories with no salience are never selected.
      </p>
      {disabled && hint ? (
        <p className="mt-2 text-sm text-[var(--fg-muted)]">{hint}</p>
      ) : null}
      <div className="mt-auto flex items-center pt-4">
        <MonoLabel>max 200</MonoLabel>
        <Button className="ml-auto" onClick={onBuild} loading={loading} disabled={disabled}>
          Build plan
        </Button>
      </div>
    </Card>
  );
}
