
function getActorId(): string | undefined {
  if (typeof window !== "undefined") {
    const stored = window.localStorage.getItem("actor_employee_id");
    if (stored) return stored;
    const env = process.env.NEXT_PUBLIC_ACTOR_EMPLOYEE_ID;
    if (env) {
      window.localStorage.setItem("actor_employee_id", env);
      return env;
    }
    return undefined;
  }
  return process.env.NEXT_PUBLIC_ACTOR_EMPLOYEE_ID;
}
export async function customFetch<T>(
  url: string,
  options: RequestInit,
): Promise<T> {
  const base = process.env.NEXT_PUBLIC_API_URL;
  if (!base) throw new Error("NEXT_PUBLIC_API_URL is not set");

  const res = await fetch(`${base}${url}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(getActorId() ? { "X-Actor-Employee-Id": String(getActorId()) } : {}),
      ...(options.headers ?? {}),
    },
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${text ? `: ${text}` : ""}`);
  }

  return (await res.json()) as T;
}
