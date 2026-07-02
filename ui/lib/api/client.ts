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
  const res = await fetch(url, {
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    ...init,
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
