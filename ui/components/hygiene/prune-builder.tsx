"use client";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { SerifHeading } from "@/components/ui/serif-heading";
import { MonoLabel } from "@/components/ui/mono-label";

type Props = {
  onBuild: () => void;
  loading: boolean;
  disabled?: boolean;
};

export function PruneBuilder({ onBuild, loading, disabled }: Props) {
  return (
    <Card variant="flat" className="flex items-center justify-between gap-6">
      <div>
        <SerifHeading title="Build a prune plan" size="section" eyebrow="DRY RUN" />
        <p className="mt-1 text-sm text-[var(--fg-muted)]">
          Selects up to 200 candidates. Identity tier and memories with no salience are never selected.
        </p>
      </div>
      <div className="flex items-center gap-3">
        <MonoLabel>max 200</MonoLabel>
        <Button onClick={onBuild} loading={loading} disabled={disabled}>
          Build plan
        </Button>
      </div>
    </Card>
  );
}
