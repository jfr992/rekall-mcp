import { MonoLabel } from "@/components/ui/mono-label";

type Props = {
  nodeCount: number;
  linkCount: number;
  refreshedAt: string;
};

export function GraphStats({ nodeCount, linkCount, refreshedAt }: Props) {
  return (
    <div className="flex items-center gap-4 rounded-full border border-[var(--border)] bg-[var(--bg-frost)] px-4 py-1.5 backdrop-blur-[12px]">
      <MonoLabel>{nodeCount} nodes</MonoLabel>
      <MonoLabel>{linkCount} edges</MonoLabel>
      <MonoLabel>refreshed {refreshedAt}</MonoLabel>
    </div>
  );
}
