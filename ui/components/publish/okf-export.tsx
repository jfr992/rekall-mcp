"use client";

import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Download, Sparkles, FileText } from "lucide-react";
import { usePublish } from "@/lib/queries/use-publish";
import {
  downloadBundleUrl,
  startSynthesis,
  getSynthesisStatus,
} from "@/lib/api/publish";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { MonoLabel } from "@/components/ui/mono-label";
import { SerifHeading } from "@/components/ui/serif-heading";
import { Empty } from "@/components/ui/empty";

interface OkfExportProps {
  project: string;
}

interface ParsedConcept {
  type?: string;
  title?: string;
  tags: string[];
  timestamp?: string;
  brief: string;
  sources: string[];
}

// The concept file is `---\n<yaml>\n---\n<body>`; body is a brief then `## Sources`.
function parseConcept(raw: string): ParsedConcept {
  const fm: Record<string, string> = {};
  let body = raw;
  const m = raw.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
  const tags: string[] = [];
  if (m) {
    body = m[2];
    let key = "";
    for (const line of m[1].split("\n")) {
      const kv = line.match(/^(\w+):\s*(.*)$/);
      if (kv) {
        key = kv[1];
        if (kv[2]) fm[key] = kv[2].replace(/^['"]|['"]$/g, "");
      } else if (line.match(/^\s*-\s+/) && key === "tags") {
        tags.push(line.replace(/^\s*-\s+/, "").trim());
      }
    }
  }
  const [beforeSources, afterSources] = body.split(/\n##\s+Sources\s*\n/);
  const sources = (afterSources ?? "")
    .split("\n")
    .filter((l) => l.trim().startsWith("- "))
    .map((l) => l.replace(/^\s*-\s+/, "").trim());
  return {
    type: fm.type,
    title: fm.title,
    tags,
    timestamp: fm.timestamp,
    brief: (beforeSources ?? "").trim(),
    sources,
  };
}

function ConceptPreview({ raw }: { raw: string }) {
  const c = useMemo(() => parseConcept(raw), [raw]);
  const notSynthesized = c.brief.startsWith("_Not yet synthesized");

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {c.type ? <Badge kind="type" value={c.type} /> : null}
          {c.timestamp ? <MonoLabel>{c.timestamp.slice(0, 10)}</MonoLabel> : null}
        </div>
        <SerifHeading title={c.title ?? "Untitled concept"} size="section" />
      </div>

      {notSynthesized ? (
        <p className="rounded-[var(--radius-md)] border border-dashed border-[var(--border)] px-4 py-3 text-sm text-[var(--fg-muted)]">
          Not yet distilled. Run Synthesize to turn these notes into a brief.
        </p>
      ) : (
        <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-[var(--fg)]">
          {c.brief}
        </p>
      )}

      {c.sources.length > 0 ? (
        <div className="space-y-2 border-t border-[var(--border)] pt-4">
          <MonoLabel>
            {c.sources.length} source{c.sources.length === 1 ? "" : "s"}
          </MonoLabel>
          <ul className="space-y-2">
            {c.sources.map((s, i) => (
              <li
                key={i}
                className="text-sm leading-relaxed text-[var(--fg-dim)] before:mr-2 before:text-[var(--fg-muted)] before:content-['\2022']"
              >
                {s}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export function OkfExport({ project }: OkfExportProps) {
  const { data, isLoading } = usePublish(project, true);
  const [selected, setSelected] = useState<string | null>(null);
  const [synth, setSynth] = useState({ running: false, done: 0, total: 0 });
  const queryClient = useQueryClient();

  // Show only real concepts in the tree — index.md files are OKF plumbing.
  const concepts = useMemo(
    () => (data?.tree ?? []).filter((p) => !p.endsWith("index.md")),
    [data]
  );

  async function runSynthesis() {
    setSynth({ running: true, done: 0, total: 0 });
    await startSynthesis(project);
    const poll = setInterval(async () => {
      const s = await getSynthesisStatus(project);
      setSynth({ running: s.status === "running", done: s.done ?? 0, total: s.total ?? 0 });
      if (s.status !== "running") {
        clearInterval(poll);
        setSynth((p) => ({ ...p, running: false }));
        queryClient.invalidateQueries({ queryKey: ["publish", project] });
      }
    }, 1500);
  }

  if (isLoading) return <div className="p-6 text-sm text-[var(--fg-muted)]">Building bundle…</div>;
  if (!data || concepts.length === 0)
    return <Empty title="Nothing to publish" hint="No memories in this scope yet." />;

  const mode = data.stats.synthesized;
  const isSynth = mode === "llm" || mode === "cached";

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5 text-sm">
          <MonoLabel>{concepts.length} concepts</MonoLabel>
          <span
            className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium uppercase tracking-[0.08em]"
            style={{
              color: isSynth ? "var(--accent-success)" : "var(--fg-muted)",
              borderColor: isSynth ? "color-mix(in oklab, var(--accent-success) 40%, transparent)" : "var(--border)",
            }}
          >
            {isSynth ? "distilled" : "raw"}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="primary"
            size="sm"
            loading={synth.running}
            onClick={runSynthesis}
          >
            <Sparkles size={14} />
            {synth.running
              ? `Distilling ${synth.done}/${synth.total || "…"}`
              : "Synthesize"}
          </Button>
          <a href={downloadBundleUrl(project)}>
            <Button variant="secondary" size="sm">
              <Download size={14} />
              Download
            </Button>
          </a>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[280px_1fr] gap-4">
        <Card variant="glass" className="min-h-0 overflow-auto p-2">
          <ul className="space-y-0.5">
            {concepts.map((p) => {
              const active = p === selected;
              const label = p.replace(/\.md$/, "").split("/").pop() ?? p;
              const dir = p.split("/").slice(0, -1).join("/");
              return (
                <li key={p}>
                  <button
                    onClick={() => setSelected(p)}
                    className={`flex w-full items-start gap-2 rounded-[var(--radius-sm)] px-2.5 py-2 text-left text-sm transition-colors duration-[var(--dur-fast)] ${
                      active
                        ? "bg-[var(--surface-1)] text-[var(--fg)]"
                        : "text-[var(--fg-dim)] hover:bg-[var(--surface-0)]"
                    }`}
                    style={active ? { boxShadow: "inset 2px 0 0 var(--accent-primary)" } : undefined}
                  >
                    <FileText size={13} className="mt-0.5 shrink-0 text-[var(--fg-muted)]" />
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate">{label}</span>
                      {dir ? (
                        <span className="truncate font-mono text-[10px] text-[var(--fg-muted)]">
                          {dir}
                        </span>
                      ) : null}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </Card>

        <Card variant="flat" className="min-h-0 overflow-auto">
          {selected ? (
            <ConceptPreview raw={data.files[selected]} />
          ) : (
            <div className="flex h-full items-center justify-center">
              <Empty title="Select a concept" hint="Pick a file to read its brief." />
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
