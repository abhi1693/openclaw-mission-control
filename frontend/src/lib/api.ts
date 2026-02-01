export function apiUrl(path: string) {
  const base = process.env.NEXT_PUBLIC_API_URL;
  if (!base) throw new Error("NEXT_PUBLIC_API_URL is not set");
  return `${base}${path}`;
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(apiUrl(path), { cache: "no-store" });
  if (!res.ok) throw new Error(`GET ${path} failed (${res.status})`);
  return (await res.json()) as T;
}

export async function apiSend<T>(
  path: string,
  opts: { method: "POST" | "PATCH" | "DELETE"; body?: unknown }
): Promise<T> {
  const res = await fetch(apiUrl(path), {
    method: opts.method,
    headers: opts.body ? { "Content-Type": "application/json" } : undefined,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) throw new Error(`${opts.method} ${path} failed (${res.status})`);
  return (await res.json()) as T;
}
