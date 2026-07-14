export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

export async function fetchJson<T>(
  path: string,
  init?: RequestInit,
  parse?: (data: unknown) => T
): Promise<T> {
  const url = path.startsWith("http") ? path : path; // Proxied via next.config rewrites
  // Optional bearer token — only sent when the backend has auth enabled.
  const token = process.env.NEXT_PUBLIC_REKALL_API_TOKEN;
  const method = (init?.method ?? "GET").toUpperCase();
  const mutating = ["POST", "PUT", "DELETE", "PATCH"].includes(method);
  const res = await fetch(url, {
    cache: "no-store",
    ...init,
    // Merged AFTER ...init so caller headers extend, never clobber, the
    // defaults — X-Rekall-UI is what the server's browser guard requires.
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(mutating ? { "X-Rekall-UI": "1" } : {}),
      ...((init?.headers as Record<string, string> | undefined) ?? {}),
    },
  });
  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = await res.text();
    }
    throw new ApiError(res.status, `Request failed: ${res.status}`, body);
  }
  const data = await res.json();
  return parse ? parse(data) : (data as T);
}
