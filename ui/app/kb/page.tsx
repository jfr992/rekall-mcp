"use client";

import { useState } from "react";
import { KbColumns } from "@/components/kb/kb-columns";
import { OkfExport } from "@/components/publish/okf-export";
import { SerifHeading } from "@/components/ui/serif-heading";
import { Empty } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { useKb } from "@/lib/queries/use-kb";
import { useProjectStore } from "@/lib/project-store";

type Tab = "curated" | "okf";

export default function KbPage() {
  const project = useProjectStore((s) => s.project);
  const { data, isLoading, isError } = useKb(project);
  const [tab, setTab] = useState<Tab>("curated");

  return (
    <div className="mx-auto flex h-[calc(100vh-3.5rem)] max-w-7xl flex-col gap-6 p-6">
      <SerifHeading eyebrow="CURATED BY TYPE · LIVE" title={`Knowledge Base · ${project}`} />

      <div className="flex gap-2 text-sm">
        <button
          className={`rounded px-3 py-1 ${tab === "curated" ? "bg-foreground text-background" : "border"}`}
          onClick={() => setTab("curated")}
        >
          Curated
        </button>
        <button
          className={`rounded px-3 py-1 ${tab === "okf" ? "bg-foreground text-background" : "border"}`}
          onClick={() => setTab("okf")}
        >
          Export OKF
        </button>
      </div>

      {tab === "okf" ? (
        <OkfExport project={project} />
      ) : isLoading ? (
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-full w-full" />
          ))}
        </div>
      ) : isError || !data ? (
        <Empty title="Could not load knowledge base" hint="Check backend connection" />
      ) : (
        <KbColumns data={data} />
      )}
    </div>
  );
}
