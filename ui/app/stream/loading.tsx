import { Skeleton } from "@/components/ui/skeleton";
export default function Loading() {
  return (
    <div className="mx-auto grid max-w-7xl grid-cols-1 gap-6 p-6 lg:grid-cols-[240px_1fr]">
      <Skeleton className="h-[420px] w-full" />
      <Skeleton className="h-[420px] w-full" />
    </div>
  );
}
