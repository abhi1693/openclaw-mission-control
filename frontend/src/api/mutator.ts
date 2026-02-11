import { getLocalAuthToken, isLocalAuthMode } from "@/auth/localAuth";

type ClerkSession = {
  getToken: () => Promise<string>;
};

type ClerkGlobal = {
  session?: ClerkSession | null;
};

export class ApiError<TData = unknown> extends Error {
  status: number;
  data: TData | null;

  constructor(status: number, message: string, data: TData | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

const resolveClerkToken = async (): Promise<string | null> => {
  if (typeof window === "undefined") {
    return null;
  }
  const clerk = (window as unknown as { Clerk?: ClerkGlobal }).Clerk;
  if (!clerk?.session) {
    return null;
  }
  try {
    return await clerk.session.getToken();
  } catch {
    return null;
  }
};

export const customFetch = async <T>(
  url: string,
  options: RequestInit,
): Promise<T> => {
  const rawBaseUrl = process.env.NEXT_PUBLIC_API_URL;
  if (!rawBaseUrl) {
    throw new Error("NEXT_PUBLIC_API_URL is not set.");
  }
  const baseUrl = rawBaseUrl.replace(/\/+$/, "");

  const headers = new Headers(options.headers);
  const hasBody = options.body !== undefined && options.body !== null;
  if (hasBody && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (isLocalAuthMode() && !headers.has("Authorization")) {
    const token = getLocalAuthToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }
  if (!headers.has("Authorization")) {
    const token = await resolveClerkToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }

  const response = await fetch(`${baseUrl}${url}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const contentType = response.headers.get("content-type") ?? "";
    let errorData: unknown = null;
    const isJson =
      contentType.includes("application/json") || contentType.includes("+json");
    if (isJson) {
      errorData = (await response.json().catch(() => null)) as unknown;
    } else {
      errorData = await response.text().catch(() => "");
    }

    let message =
      typeof errorData === "string" && errorData ? errorData : "Request failed";
    if (errorData && typeof errorData === "object") {
      const detail = (errorData as { detail?: unknown }).detail;
      if (typeof detail === "string" && detail) {
        message = detail;
      } else if (Array.isArray(detail) && detail.length) {
        const first = detail[0] as { msg?: unknown };
        if (
          first &&
          typeof first === "object" &&
          typeof first.msg === "string"
        ) {
          message = first.msg;
        }
      }
    }
    throw new ApiError(response.status, message, errorData);
  }

  if (response.status === 204) {
    return {
      data: undefined,
      status: response.status,
      headers: response.headers,
    } as T;
  }

  const contentType = response.headers.get("content-type") ?? "";
  const isJson =
    contentType.includes("application/json") || contentType.includes("+json");
  if (isJson) {
    const data = (await response.json()) as unknown;
    return { data, status: response.status, headers: response.headers } as T;
  }
  if (contentType.includes("text/event-stream")) {
    return {
      data: response,
      status: response.status,
      headers: response.headers,
    } as T;
  }
  const text = await response.text().catch(() => "");
  return {
    data: text,
    status: response.status,
    headers: response.headers,
  } as T;
};
