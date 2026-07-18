// Origins observed in the event tail: v2 payload capture_origin, v1 event source.
const LABELS: Record<string, string> = {
  session_start: "session start",
  startup: "session start",
  capsule: "capsule",
  reflex: "reflex check",
  cross_project: "cross-project recall",
};

export function recallOriginLabel(origin: string | null | undefined): string {
  return (origin && LABELS[origin]) || "background recall";
}
