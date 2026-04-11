"use client";

import { useEffect, useMemo, useState } from 'react';
import { BrainCanvas } from './brain-canvas';
import { HandoffPanel } from './handoff-panel';
import { KbPanel } from './kb-panel';
import { PressurePanel } from './pressure-panel';
import { getGraph, getHealth, getStartup, type GraphResponse, type HealthResponse, type StartupResponse } from '../lib/api';

export function Dashboard() {
  const [project, setProject] = useState('general');
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [startup, setStartup] = useState<StartupResponse | null>(null);
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<string>('');

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [healthData, startupData, graphData] = await Promise.all([
          getHealth(),
          getStartup(project, 'claude-code'),
          getGraph(project, 120),
        ]);
        if (cancelled) return;
        setHealth(healthData);
        setStartup(startupData);
        setGraph(graphData);
        setError(null);
        setUpdatedAt(new Date().toLocaleTimeString());
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Unknown error');
      }
    }

    load();
    const interval = window.setInterval(load, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [project]);

  const nodeCount = useMemo(() => graph?.graph?.nodes?.length ?? 0, [graph]);
  const linkCount = useMemo(() => graph?.graph?.links?.length ?? 0, [graph]);
  const graphNodes = useMemo(() => (graph?.graph?.nodes ?? []) as Array<{ id: string; type?: string; content?: string; degree?: number }>, [graph]);
  const graphLinks = useMemo(() => (graph?.graph?.links ?? []) as Array<{ source: string; target: string; weight?: number }>, [graph]);
  const pulseKey = `${updatedAt}-${nodeCount}-${linkCount}`;

  return (
    <main className="page">
      <div className="hero">
        <div className="hero-copy">
          <span className="eyebrow">MEMENTO MEMORY COCKPIT</span>
          <h1>Brain + KB cockpit</h1>
          <p>
            A live interface for memory state, graph activity, continuity, and operational hygiene.
          </p>
        </div>
        <div className="controls">
          <label>
            Project
            <input value={project} onChange={(e) => setProject(e.target.value)} />
          </label>
        </div>
      </div>

      {error ? <div className="error">Backend error: {error}</div> : null}

      <section className="cockpit">
        <article className="brain-shell">
          <div className="brain-header">
            <div>
              <h2>Neural Graph</h2>
              <p>Live pulse over the current memory graph.</p>
            </div>
            <div className="brain-stats">
              <span>{nodeCount} nodes</span>
              <span>{linkCount} links</span>
              <span>{updatedAt || 'refreshing'}</span>
            </div>
          </div>
          <BrainCanvas nodes={graphNodes} links={graphLinks} pulseKey={pulseKey} />
        </article>

        <aside className="sidebar">
          <article className="card">
            <h2>System Health</h2>
            <p>Status: <strong>{health?.status ?? 'loading'}</strong></p>
            <p>Transport: {health?.transport ?? '...'}</p>
            <p>Tools: {(health?.tools_enabled ?? []).join(', ') || '...'}</p>
          </article>

          <KbPanel
            project={startup?.scope?.project ?? project}
            agent={startup?.scope?.agent ?? 'claude-code'}
            nodeCount={nodeCount}
            linkCount={linkCount}
            hints={startup?.system_hints ?? []}
          />

          <HandoffPanel summary={startup?.resume_packet?.handoff ?? startup?.startup_summary ?? ''} />

          <PressurePanel summary={String(startup?.resume_packet?.pressure_report ?? '')} />
        </aside>
      </section>
    </main>
  );
}
