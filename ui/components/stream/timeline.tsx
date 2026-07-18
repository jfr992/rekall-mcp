import { Fragment } from "react";
import { Badge } from "@/components/ui/badge";
import { Empty } from "@/components/ui/empty";
import { ShowMoreList } from "@/components/ui/show-more-list";
import { recallOriginLabel } from "@/lib/recall-origin";
import type { StreamRow } from "@/lib/schemas";

type Props = {
  rows: StreamRow[];
};

const VISIBLE_PER_DAY = 20;

function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function dayLabel(at: string, now: number): string {
  const d = new Date(at);
  const monthDay = d
    .toLocaleDateString("en-US", { month: "short", day: "numeric" })
    .toUpperCase();
  if (sameDay(d, new Date(now))) return `TODAY · ${monthDay}`;
  if (sameDay(d, new Date(now - 24 * 60 * 60 * 1000))) return "YESTERDAY";
  return monthDay;
}

function timeLabel(at: string): string {
  const d = new Date(at);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function strengthBar(durability: number): string {
  const filled = Math.min(5, Math.max(0, Math.round(durability * 5)));
  return "▓".repeat(filled) + "░".repeat(5 - filled);
}

function SavedRow({ row }: { row: Extract<StreamRow, { kind: "saved" }> }) {
  const { payload } = row;
  const decaying = payload.tier === "working" && payload.fades_in_hours != null;
  return (
    <div
      data-decaying={decaying || undefined}
      className={`rounded-lg border p-3 ${
        decaying
          ? "border-dashed border-[var(--border-strong)] bg-[var(--bg-elevated)] opacity-45"
          : "border-[var(--border)] bg-[var(--bg-raised)]"
      }`}
    >
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <Badge kind="type" value={payload.type} />
        {payload.tier ? <Badge kind="tier" value={payload.tier} /> : null}
        {payload.durability != null ? (
          <span className="ml-auto font-mono text-[10px] text-[var(--fg-dim)]">
            strength {strengthBar(payload.durability)} {payload.durability.toFixed(1)}
          </span>
        ) : null}
        {decaying ? (
          <span className="font-mono text-[10px] text-[var(--accent-danger)]">
            fades in {payload.fades_in_hours}h
          </span>
        ) : null}
      </div>
      <p className="text-sm leading-relaxed text-[var(--fg)]">{payload.preview}</p>
    </div>
  );
}

function RecalledRow({ row }: { row: Extract<StreamRow, { kind: "recalled" }> }) {
  const { payload } = row;
  const n = payload.memory_ids.length;
  const surfaced = `${n} ${n === 1 ? "memory" : "memories"} surfaced`;
  return (
    <div className="flex flex-wrap items-center gap-2.5 rounded-lg border border-dashed border-[color:rgba(163,230,53,0.3)] p-3">
      <span className="font-mono text-[10px] font-medium tracking-[0.1em] text-[var(--accent-success)]">
        RECALLED
      </span>
      <span className="text-[13px] text-[var(--fg-muted)]">
        {payload.query !== null
          ? `“${payload.query}”`
          : recallOriginLabel(payload.capture_origin)}{" "}
        → {surfaced}
        {payload.top_score != null ? `, top match ${payload.top_score.toFixed(2)}` : ""}
      </span>
    </div>
  );
}

function PromotedRow({ row }: { row: Extract<StreamRow, { kind: "promoted" }> }) {
  const { payload } = row;
  return (
    <div className="flex flex-wrap items-center gap-2.5 rounded-lg border border-[color:rgba(167,139,250,0.35)] bg-gradient-to-r from-[color:rgba(167,139,250,0.1)] to-transparent p-3">
      <span className="font-mono text-[10px] font-medium tracking-[0.1em] text-[var(--accent-secondary)]">
        PROMOTED
      </span>
      <span className="text-[13px] text-[var(--fg-soft)]">
        {payload.memory_id} · {payload.from_tier ?? "?"} → {payload.to_tier ?? "?"}
      </span>
    </div>
  );
}

function ConsolidatedRow({ row }: { row: Extract<StreamRow, { kind: "consolidated" }> }) {
  const { payload } = row;
  return (
    <div className="flex flex-wrap items-center gap-2.5 rounded-lg border border-[color:rgba(167,139,250,0.35)] bg-gradient-to-r from-[color:rgba(167,139,250,0.1)] to-transparent p-3">
      <span className="font-mono text-[10px] font-medium tracking-[0.1em] text-[var(--accent-secondary)]">
        CONSOLIDATED
      </span>
      <span className="text-[13px] text-[var(--fg-soft)]">{payload.preview}</span>
    </div>
  );
}

function Row({ row }: { row: StreamRow }) {
  switch (row.kind) {
    case "saved":
      return <SavedRow row={row} />;
    case "recalled":
      return <RecalledRow row={row} />;
    case "promoted":
      return <PromotedRow row={row} />;
    case "consolidated":
      return <ConsolidatedRow row={row} />;
  }
}

function RowLine({ row }: { row: StreamRow }) {
  return (
    <div className="grid grid-cols-[48px_1fr] items-start gap-3">
      <span className="pt-3 text-right font-mono text-[10px] text-[var(--fg-dim)]">
        {timeLabel(row.at)}
      </span>
      <Row row={row} />
    </div>
  );
}

type Group = { label: string; rows: StreamRow[] };

function groupByDay(rows: StreamRow[], now: number): Group[] {
  const groups: Group[] = [];
  for (const row of rows) {
    const label = dayLabel(row.at, now);
    const current = groups[groups.length - 1];
    if (current && current.label === label) {
      current.rows.push(row);
    } else {
      groups.push({ label, rows: [row] });
    }
  }
  return groups;
}

export function Timeline({ rows }: Props) {
  const now = Date.now();
  if (rows.length === 0) {
    return (
      <Empty
        title="No activity yet"
        hint="Memories and recalls appear here as they happen"
      />
    );
  }
  const groups = groupByDay(rows, now);
  return (
    <div className="flex flex-col gap-3.5">
      {groups.map((group, gi) => (
        <Fragment key={`${group.label}-${gi}`}>
          <div
            className={`font-mono text-[10px] font-medium tracking-[0.14em] ${
              group.label.startsWith("TODAY")
                ? "text-[var(--accent-bright)]"
                : "text-[var(--fg-dim)]"
            } ${gi > 0 ? "mt-2" : ""}`}
          >
            {group.label}
          </div>
          <div className="flex flex-col gap-3.5">
            <ShowMoreList
              items={group.rows}
              initialCount={VISIBLE_PER_DAY}
              keyFor={(row, i) => `${row.at}-${i}`}
              moreLabel={(n) => `Show ${n} more from this day`}
              renderItem={(row) => <RowLine row={row} />}
            />
          </div>
        </Fragment>
      ))}
    </div>
  );
}
