import type { PressureResponse } from "@/lib/schemas";

export function PressureExplainer({ data }: { data: PressureResponse }) {
  const score = data.load_score;
  const state = score < 0.2 ? "quiet" : score < 0.5 ? "active" : "saturated";
  const stateColor =
    score < 0.2
      ? "var(--accent-success)"
      : score < 0.5
      ? "var(--accent-warning)"
      : "var(--accent-danger)";
  const candidateCount =
    data.flagged.stale_working_count + data.flagged.low_value_count;
  return (
    <p className="text-sm text-[var(--fg-muted)]">
      This project is <span style={{ color: stateColor }}>{state}</span>.
      {" "}
      {candidateCount} {candidateCount === 1 ? "memory is a candidate" : "memories are candidates"} for prune.
    </p>
  );
}
