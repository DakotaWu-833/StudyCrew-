import { apiFetch, jsonBody } from "./client";

export interface AccountDevice {
  id: string;
  browser: string;
  first_seen_at: string;
  last_seen_at: string;
  expires_at: string;
  current: boolean;
}

export interface AccountSecuritySummary {
  recovery_email: { email: string; verified_at: string } | null;
  devices: AccountDevice[];
  owned_projects: { project_id: string; project__name: string }[];
  privacy: { version: string; visibility: string[]; retention: string[]; download: string };
  verification_minutes: number;
}

const base = "/api/v1/account/";
const post = <T>(path: string, body: unknown = {}) => apiFetch<T>(`${base}${path}`, { method: "POST", ...jsonBody(body) });

export const accountReadinessApi = {
  summary: () => apiFetch<AccountSecuritySummary>(`${base}security/`),
  reauthenticate: (current_password: string) => post<{ message: string; valid_for_seconds: number }>("reauthenticate/", { current_password }),
  requestRecoveryEmail: (email: string) => post<{ message: string }>("recovery-email/", { email }),
  removeRecoveryEmail: () => apiFetch<{ message: string }>(`${base}recovery-email/`, { method: "DELETE" }),
  revokeDevice: (id: string) => post<{ message: string; signed_out: boolean }>(`devices/${encodeURIComponent(id)}/revoke/`),
  revokeOthers: () => post<{ message: string }>("devices/revoke-others/"),
  download: () => post<unknown>("data/download/"),
  close: (confirmation: string) => post<{ message: string }>("close/", { confirmation }),
};
