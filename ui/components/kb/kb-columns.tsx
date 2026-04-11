import { KbSlice } from "./kb-slice";
import type { KbResponse } from "@/lib/schemas";

type Props = {
  data: KbResponse;
};

export function KbColumns({ data }: Props) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
      <KbSlice title="Decisions" accentVar="var(--accent-warning)" entries={data.decisions} />
      <KbSlice title="Requirements" accentVar="var(--accent-danger)" entries={data.requirements} />
      <KbSlice title="Preferences" accentVar="var(--accent-secondary)" entries={data.preferences} />
      <KbSlice title="Learnings" accentVar="var(--accent-success)" entries={data.learnings} />
    </div>
  );
}
