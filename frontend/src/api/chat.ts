import { apiFetch, jsonBody } from "./client";
import type { UserSummary } from "./types";

export interface ChatMessage { id: string; author: UserSummary; body: string; created_at: string; updated_at: string; removed: boolean; hidden: boolean; can_remove: boolean }
export interface ChatState { messages: ChatMessage[]; cursor: number; has_more: boolean; older_than: string | null; online: UserSummary[]; read_only: boolean; poll_seconds: number; visibility_key: string }
const base = (project: string) => `/api/v1/chat/projects/${project}/`;
export const chatApi = {
  list: (project: string, values: { since?: number; before?: string } = {}) => {
    const params = new URLSearchParams();
    if (values.since !== undefined) params.set("since", String(values.since));
    if (values.before) params.set("before", values.before);
    return apiFetch<ChatState>(`${base(project)}messages/?${params}`, { cache: "no-store" });
  },
  send: (project: string, body: string, nonce: string) => apiFetch<ChatMessage>(`${base(project)}messages/`, { method: "POST", ...jsonBody({ body, client_nonce: nonce }) }),
  remove: (project: string, message: ChatMessage, reason: string) => apiFetch<ChatMessage>(`${base(project)}messages/${message.id}/remove/`, { method: "POST", ...jsonBody({ expected_updated_at: message.updated_at, reason }) }),
  presence: (project: string) => apiFetch<void>(`${base(project)}presence/`, { method: "POST", ...jsonBody({}) }),
};
