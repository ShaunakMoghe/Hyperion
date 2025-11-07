const DEFAULT_BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

type FetchOptions = {
  method?: string;
  body?: unknown;
  cache?: RequestCache;
};

export async function fetchJson<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const { method = "GET", body, cache = "no-store" } = options;
  const response = await fetch(`${DEFAULT_BACKEND_URL}${path}`, {
    method,
    cache,
    headers: {
      "Content-Type": "application/json"
    },
    body: body ? JSON.stringify(body) : undefined
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Request failed (${response.status}): ${errorText}`);
  }

  return (await response.json()) as T;
}

export async function listOrganizations() {
  return fetchJson<Array<{ id: string; name: string; slug: string }>>("/orgs/");
}

export async function createOrganization(payload: { name: string; slug?: string }) {
  return fetchJson<{ id: string; name: string; slug: string }>("/orgs/", {
    method: "POST",
    body: payload
  });
}

export async function listAuditLogs() {
  return fetchJson<Array<{ id: string; action: string; created_at: string; target?: string }>>("/audit/");
}
