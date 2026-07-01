"use client";

import { useState } from "react";
import { usePublish } from "@/lib/queries/use-publish";
import { downloadBundleUrl } from "@/lib/api/publish";

interface OkfExportProps {
  project: string;
}

export function OkfExport({ project }: OkfExportProps) {
  const { data, isLoading } = usePublish(project, true);
  const [selected, setSelected] = useState<string | null>(null);

  if (isLoading) return <div className="p-4 text-sm">Building bundle…</div>;
  if (!data || data.tree.length === 0)
    return <div className="p-4 text-sm text-muted-foreground">No memories for this scope.</div>;

  return (
    <div className="grid min-h-0 flex-1 grid-cols-[280px_1fr] gap-4">
      <ul className="min-h-0 overflow-auto space-y-1 text-sm">
        {data.tree.map((p) => (
          <li key={p}>
            <button
              className="w-full text-left hover:underline"
              onClick={() => setSelected(p)}
            >
              {p}
            </button>
          </li>
        ))}
      </ul>
      <div className="flex min-h-0 flex-col">
        <a
          href={downloadBundleUrl(project)}
          className="mb-2 inline-block w-fit rounded border px-3 py-1 text-sm"
        >
          Download .tar.gz
        </a>
        <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap rounded bg-muted p-3 text-sm">
          {selected ? data.files[selected] : "Select a file to preview."}
        </pre>
        <p className="mt-2 text-xs text-muted-foreground">
          {data.stats.concepts} concepts · titled by {data.stats.titled_by ?? "slug"}
        </p>
      </div>
    </div>
  );
}
