export type HealthResponse = {
  status: string;
  transport?: string;
  tools_enabled?: string[];
};

export type StartupResponse = {
  scope: { project: string; agent: string; repo_name?: string; branch?: string };
  startup_summary: string;
  resume_packet: {
    handoff?: string;
    pressure_report?: string;
    [key: string]: unknown;
  };
  system_hints: string[];
};

export type GraphResponse = {
  graph?: {
    nodes?: Array<Record<string, unknown>>;
    links?: Array<Record<string, unknown>>;
  };
};

const BASE_URL = process.env.NEXT_PUBLIC_MEMENTO_API_URL ?? 'http://localhost:8000';

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function getHealth(): Promise<HealthResponse> {
  return fetchJson<HealthResponse>('/health');
}

export function getStartup(project = 'general', agent = 'claude-code'): Promise<StartupResponse> {
  return fetchJson<StartupResponse>(`/api/memory/context/startup?project=${encodeURIComponent(project)}&agent=${encodeURIComponent(agent)}`);
}

export function getGraph(project = 'general', limit = 120): Promise<GraphResponse> {
  return fetchJson<GraphResponse>(`/api/memory/graph?project=${encodeURIComponent(project)}&limit=${limit}`);
}
