"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { usePublish } from "@/lib/queries/use-publish";
import {
  downloadBundleUrl,
  startSynthesis,
  getSynthesisStatus,
} from "@/lib/api/publish";

interface OkfExportProps {
  project: string;
}

export function OkfExport({ project }: OkfExportProps) {
  const { data, isLoading } = usePublish(project, true);
  const [selected, setSelected] = useState<string | null>(null);
  const [synth, setSynth] = useState<{ running: boolean; done: number; total: number }>(
    { running: false, done: 0, total: 0 }
  );
  const queryClient = useQueryClient();

  async function runSynthesis() {
    setSynth({ running: true, done: 0, total: 0 });
    await startSynthesis(project);
    const poll = setInterval(async () => {
      const s = await getSynthesisStatus(project);
      setSynth({ running: s.status === "running", done: s.done ?? 0, total: s.total ?? 0 });
      if (s.status === "done" || s.status === "error" || s.status === "idle") {
        clearInterval(poll);
        setSynth((p) => ({ ...p, running: false }));
        queryClient.invalidateQueries({ queryKey: ["publish", project] });
      }
    }, 1500);
  }

  if (isLoading) return <div className="p-4 text-sm">Building bundle…</div>;
  if (!data || data.tree.length === 0)
    return <div className="p-4 text-sm text-muted-foreground">No memories for this scope.</div>;

  const synthesized = data.stats.synthesized;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="flex items-center gap-3 text-sm">
        <a href={downloadBundleUrl(project)} className="rounded border px-3 py-1">
          Download .tar.gz
        </a>
        <button
          className="rounded border px-3 py-1 disabled:opacity-50"
          onClick={runSynthesis}
          disabled={synth.running}
        >
          {synth.running
            ? `Synthesizing… ${synth.done}/${synth.total || "?"}`
            : "Synthesize (LLM briefs)"}
        </button>
        <span className="text-xs text-muted-foreground">
          {data.stats.concepts} concepts · {synthesized === "llm" || synthesized === "cached" ? "synthesized" : "raw"}
        </span>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[280px_1fr] gap-4">
        <ul className="min-h-0 overflow-auto space-y-1 text-sm">
          {data.tree.map((p) => (
            <li key={p}>
              <button className="w-full text-left hover:underline" onClick={() => setSelected(p)}>
                {p}
              </button>
            </li>
          ))}
        </ul>
        <pre className="min-h-0 overflow-auto whitespace-pre-wrap rounded bg-muted p-3 text-sm">
          {selected ? data.files[selected] : "Select a file to preview."}
        </pre>
      </div>
    </div>
  );
}
