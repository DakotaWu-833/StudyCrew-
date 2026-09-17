import type { Page } from "./types";

export interface APIErrorPayload {
  error?: {
    code?: string;
    message?: string;
    fields?: Record<string, string[] | string>;
  };
}

export class APIError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fields: Record<string, string[] | string>;

  constructor(status: number, payload: APIErrorPayload) {
    super(payload.error?.message ?? "The request could not be completed.");
    this.name = "APIError";
    this.status = status;
    this.code = payload.error?.code ?? "request_failed";
    this.fields = payload.error?.fields ?? {};
  }
}

export function cookie(name: string): string {
  const pair = document.cookie
    .split(";")
    .map((item) => item.trim())
    .find((item) => item.startsWith(`${name}=`));
  return pair ? decodeURIComponent(pair.slice(name.length + 1)) : "";
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (!new Set(["GET", "HEAD", "OPTIONS", "TRACE"]).has(method)) {
    headers.set("X-CSRFToken", cookie("csrftoken"));
  }

  const response = await fetch(path, { ...init, method, headers, credentials: "same-origin" });
  if (response.status === 401) {
    window.location.assign(`/account/login/?next=${encodeURIComponent(window.location.pathname)}`);
    throw new APIError(401, { error: { code: "not_authenticated", message: "Please sign in again." } });
  }
  if (!response.ok) {
    let payload: APIErrorPayload = {};
    try { payload = await response.json() as APIErrorPayload; } catch { /* retain safe fallback */ }
    throw new APIError(response.status, payload);
  }
  if (response.status === 204) return undefined as T;
  return await response.json() as T;
}

export async function apiFetchAll<T>(path: string): Promise<Page<T>> {
  const results: T[] = [];
  const visited = new Set<string>();
  let next: string | null = path;

  while (next) {
    if (visited.has(next) || visited.size >= 100) {
      throw new APIError(502, {
        error: { code: "invalid_pagination", message: "The complete list could not be loaded." },
      });
    }
    visited.add(next);
    const page: Page<T> = await apiFetch<Page<T>>(next);
    results.push(...page.results);
    if (!page.next) break;
    const parsed = new URL(page.next, window.location.origin);
    if (parsed.origin !== window.location.origin) {
      throw new APIError(502, {
        error: { code: "invalid_pagination", message: "The complete list could not be loaded." },
      });
    }
    next = `${parsed.pathname}${parsed.search}`;
  }

  return { count: results.length, next: null, previous: null, results };
}

export function jsonBody(value: unknown): Pick<RequestInit, "body"> {
  return { body: JSON.stringify(value) };
}

export function errorMessage(error: unknown): string {
  if (error instanceof APIError) {
    const details = Object.entries(error.fields).map(([field, messages]) => {
      const label = field.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
      const text = Array.isArray(messages) ? messages.join(" ") : messages;
      return `${label}: ${text}`;
    });
    if (details.length) return `Please correct these fields. ${details.join(" ")}`;
  }
  return error instanceof Error ? error.message : "The request could not be completed.";
}
