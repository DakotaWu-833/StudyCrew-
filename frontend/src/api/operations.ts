import { apiFetch, jsonBody } from "./client";

export interface NotificationPreferences {
  in_app: boolean; email: boolean; task_reminders: boolean; meeting_reminders: boolean;
  assignments: boolean; mentions: boolean; invitations: boolean; meeting_changes: boolean;
  digest: "off" | "daily" | "weekly"; quiet_start: string | null; quiet_end: string | null;
}
export interface Alert { id: string; project: string; project_name: string; category: string; title: string; body: string; target_url: string; created_at: string; read_at: string | null }
export interface Delivery { id: string; subject: string; category: string; status: string; created_at: string; available_at: string; accepted_at: string | null; confirmed_at: string | null; attempts: number; failure_reason: string }
export interface SupportTicket { id: string; category: string; subject: string; description: string; status: string; resolution: string; requester_name?: string; created_at: string; updated_at: string; replies: { id: string; author_name: string; body: string; created_at: string }[] }
export interface ContactRequest { id: string; email: string; category: string; subject: string; description: string; created_at: string; verified_at: string; resolved_at: string | null; response: string }
export interface ServiceNotice { id: string; title: string; body: string; severity: string; starts_at: string; ends_at: string | null }
export interface OperationsSummary { backup?: { healthy: boolean; last_verified_at: string | null; max_age_hours: number }; mail: Record<string, number>; oldest_queued_at: string | null; workers: { name: string; last_run_at: string; detail: unknown }[]; requests: { id: number; day: string; route_group: string; requests: number; errors: number; total_ms: number }[]; open_support: number; weekly_active_teams: number; active_memberships: number; mail_budget: { daily_limit: number } }
export interface Paged<T> { results: T[]; page?: number; pages?: number; total?: number; page_size?: number }
const base = "/api/v1/operations/";
export const operationsApi = {
  preferences: () => apiFetch<NotificationPreferences>(`${base}preferences/`),
  updatePreferences: (value: Partial<NotificationPreferences>) => apiFetch<NotificationPreferences>(`${base}preferences/`, { method: "PATCH", ...jsonBody(value) }),
  mutes: () => apiFetch<{ results: { project: string; muted: boolean }[] }>(`${base}project-mutes/`),
  mute: (project: string, muted: boolean) => apiFetch(`${base}project-mutes/`, { method: "POST", ...jsonBody({ project, muted }) }),
  alerts: (page = 1) => apiFetch<Paged<Alert> & { count: number }>(`${base}alerts/?page=${page}`),
  readAlert: (id: string) => apiFetch<Alert>(`${base}alerts/${id}/read/`, { method: "PATCH" }),
  readAll: () => apiFetch(`${base}alerts/`, { method: "POST" }),
  deliveries: (page = 1) => apiFetch<Paged<Delivery>>(`${base}deliveries/?page=${page}`),
  tickets: (page = 1) => apiFetch<Paged<SupportTicket>>(`${base}support/?page=${page}`),
  createTicket: (value: { category: string; subject: string; description: string }) => apiFetch<SupportTicket>(`${base}support/`, { method: "POST", ...jsonBody(value) }),
  reply: (id: string, body: string) => apiFetch<SupportTicket>(`${base}support/${id}/replies/`, { method: "POST", ...jsonBody({ body }) }),
  blocks: () => apiFetch<{ results: { user_id: string; display_name: string }[] }>(`${base}blocks/`),
  block: (user_id: string, blocked: boolean) => apiFetch(`${base}blocks/`, { method: "POST", ...jsonBody({ user_id, blocked }) }),
  notices: () => apiFetch<{ results: ServiceNotice[] }>(`${base}notices/`),
  summary: () => apiFetch<OperationsSummary>(`${base}admin/summary/`),
  adminTickets: (page = 1) => apiFetch<Paged<SupportTicket>>(`${base}admin/support/?page=${page}`),
  adminContacts: (page = 1) => apiFetch<Paged<ContactRequest>>(`${base}admin/contacts/?page=${page}`),
  respondContact: (id: string, response: string) => apiFetch<ContactRequest>(`${base}admin/contacts/${id}/response/`, { method: "POST", ...jsonBody({ response }) }),
  updateTicket: (id: string, value: { status: string; resolution: string }) => apiFetch<SupportTicket>(`${base}admin/support/${id}/`, { method: "PATCH", ...jsonBody(value) }),
  adminDeliveries: (page = 1) => apiFetch<Paged<Delivery>>(`${base}admin/deliveries/?page=${page}`),
  retryDelivery: (id: string, reason: string, acknowledge_uncertain_delivery: boolean) => apiFetch<Delivery>(`${base}admin/deliveries/${id}/retry/`, { method: "POST", ...jsonBody({ reason, acknowledge_uncertain_delivery }) }),
  createNotice: (value: { title: string; body: string; severity: string; starts_at: string; ends_at: string | null }) => apiFetch<ServiceNotice>(`${base}notices/`, { method: "POST", ...jsonBody(value) }),
  endNotice: (id: string) => apiFetch<ServiceNotice>(`${base}notices/${id}/end/`, { method: "PATCH" }),
};
