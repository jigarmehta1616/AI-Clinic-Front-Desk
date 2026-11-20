import createClient from "openapi-fetch";

import type { components, paths } from "./schema";
import { sessionFromTokens, sessionStore } from "./session";

export type Schemas = components["schemas"];

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function toApiError(status: number, body: unknown): ApiError {
  const err = (body as { error?: { code?: string; message?: string; details?: Record<string, unknown> } })?.error;
  if (err?.code) return new ApiError(status, err.code, err.message ?? "Request failed", err.details ?? {});
  if (status === 0) return new ApiError(0, "network_error", "Can't reach the server. Check your connection.");
  return new ApiError(status, `http_${status}`, "Something went wrong. Please try again.");
}

let refreshing: Promise<boolean> | null = null;

/** Single-flight refresh: concurrent 401s share one rotation (reuse of a rotated token revokes the family). */
export function refreshSession(): Promise<boolean> {
  refreshing ??= (async () => {
    try {
      const res = await fetch("/api/v1/auth/refresh", { method: "POST", credentials: "same-origin" });
      if (!res.ok) {
        sessionStore.set(null);
        return false;
      }
      sessionStore.set(sessionFromTokens((await res.json()) as Schemas["TokenResponse"]));
      return true;
    } catch {
      return false;
    } finally {
      refreshing = null; // callers that arrive after it settled start a fresh rotation
    }
  })();
  return refreshing;
}

function withToken(req: Request): Request {
  const token = sessionStore.get()?.accessToken;
  if (token) req.headers.set("Authorization", `Bearer ${token}`);
  return req;
}

/** Endpoints that must not trigger refresh-and-retry (they are the auth handshake itself). */
const NO_RETRY = ["/api/v1/auth/refresh", "/api/v1/auth/otp/", "/api/v1/auth/logout"];

export async function authFetch(request: Request): Promise<Response> {
  const retry = request.clone();
  const res = await fetch(withToken(request));
  if (res.status !== 401 || NO_RETRY.some((p) => new URL(request.url, location.origin).pathname.startsWith(p))) return res;
  if (await refreshSession()) return fetch(withToken(retry));
  return res;
}

export const api = createClient<paths>({
  baseUrl: typeof location === "undefined" ? "" : location.origin, // absolute URLs: same origin as the app
  fetch: authFetch,
  credentials: "same-origin",
});

/** Turns an openapi-fetch result into data or a thrown ApiError (for TanStack Query). */
export async function unwrap<T>(
  promise: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result: { data?: T; error?: unknown; response: Response };
  try {
    result = await promise;
  } catch {
    throw toApiError(0, null);
  }
  if (!result.response.ok) throw toApiError(result.response.status, result.error);
  return result.data as T;
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === "validation_error") return "Please check the highlighted fields.";
    return e.message;
  }
  return "Something went wrong. Please try again.";
}
