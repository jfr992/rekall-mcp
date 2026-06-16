"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { MonoLabel } from "@/components/ui/mono-label";
import { Badge } from "@/components/ui/badge";
import { Empty } from "@/components/ui/empty";
import type { PrunePlan } from "@/lib/schemas";

type Props = {
  plan: PrunePlan;
  children: (ctx: { expired: boolean }) => React.ReactNode;
};

function formatMs(ms: number): string {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function PrunePlanReview({ plan, children }: Props) {
  const expiresAt = new Date(plan.expires_at).getTime();
  const [remaining, setRemaining] = useState<number>(expiresAt - Date.now());

  useEffect(() => {
    const id = setInterval(() => setRemaining(expiresAt - Date.now()), 1000);
    return () => clearInterval(id);
  }, [expiresAt]);

  const expired = remaining <= 0;

  return (
    <Card variant="flat" className="space-y-4">
      <header className="flex items-center justify-between gap-4">
        <div>
          <MonoLabel>plan id</MonoLabel>
          <div className="mt-1 select-all font-mono text-sm text-[var(--fg)]">{plan.plan_id}</div>
        </div>
        <div className="text-right">
          <MonoLabel>expires in</MonoLabel>
          <div
            className="mt-1 font-mono text-2xl"
            style={{ color: expired ? "var(--fg-dim)" : "var(--fg)" }}
          >
            {expired ? "expired" : formatMs(remaining)}
          </div>
        </div>
      </header>

      {plan.candidates.length === 0 ? (
        <Empty title="Nothing to prune. Pressure is low." />
      ) : (
        <div className="overflow-hidden rounded-md border border-[var(--border)]">
          <table className="w-full text-left text-sm">
            <thead className="bg-[var(--surface-0)]">
              <tr>
                <th className="px-3 py-2 font-mono text-[11px] uppercase tracking-[0.08em] text-[var(--fg-muted)]">memory id</th>
                <th className="px-3 py-2 font-mono text-[11px] uppercase tracking-[0.08em] text-[var(--fg-muted)]">tier</th>
                <th className="px-3 py-2 font-mono text-[11px] uppercase tracking-[0.08em] text-[var(--fg-muted)]">age</th>
                <th className="px-3 py-2 font-mono text-[11px] uppercase tracking-[0.08em] text-[var(--fg-muted)]">salience</th>
                <th className="px-3 py-2 font-mono text-[11px] uppercase tracking-[0.08em] text-[var(--fg-muted)]">reason</th>
              </tr>
            </thead>
            <tbody>
              {plan.candidates.map((c) => (
                <tr key={c.memory_id} className="border-t border-[var(--border)]">
                  <td className="px-3 py-2 font-mono text-xs text-[var(--fg)]">{c.memory_id}</td>
                  <td className="px-3 py-2"><Badge kind="tier" value={c.tier} /></td>
                  <td className="px-3 py-2 font-mono text-xs text-[var(--fg-muted)]">{c.age_days}d</td>
                  <td className="px-3 py-2 font-mono text-xs text-[var(--fg-muted)]">{c.salience.toFixed(2)}</td>
                  <td className="px-3 py-2 text-xs text-[var(--fg-muted)]">{c.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {children({ expired })}
    </Card>
  );
}
