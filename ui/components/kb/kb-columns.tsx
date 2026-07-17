import { KbSlice } from "./kb-slice";
import type { KbResponse } from "@/lib/schemas";

type Props = {
  data: KbResponse;
};

export function KbColumns({ data }: Props) {
  // Slice accents are the memory-type tokens so KB, badges, and palette dots agree.
  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-hidden md:grid-cols-2 xl:grid-cols-5">
      <KbSlice title="Decisions" accentVar="var(--type-decision)" entries={data.decisions} />
      <KbSlice title="Requirements" accentVar="var(--type-requirement)" entries={data.requirements} />
      <KbSlice title="Preferences" accentVar="var(--type-preference)" entries={data.preferences} />
      <KbSlice title="Learnings" accentVar="var(--type-learning)" entries={data.learnings} />
      <KbSlice title="Facts" accentVar="var(--type-fact)" entries={data.facts ?? []} />
    </div>
  );
}
