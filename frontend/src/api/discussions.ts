import { apiFetch, jsonBody } from "./client";
import type { Paged } from "./operations";

export interface PostReply { id: string; body: string; author: { id: string; display_name: string }; created_at: string; removed_at: string | null; can_remove: boolean }
export interface ProjectPost { id: string; project: string; title: string; body: string; kind: "discussion" | "announcement"; pinned: boolean; mention_ids: string[]; author: { id: string; display_name: string }; created_at: string; updated_at: string; removed_at: string | null; can_edit: boolean; manager: boolean; read_only: boolean; replies: PostReply[]; reply_pagination?: { page: number; pages: number; total: number } }
export interface PostReport { id: string; ticket_id: string; title: string; snapshot: string; description: string; status: string; resolution: string; created_at: string }
const base = "/api/v1/operations/";
export const discussionsApi = {
  list: (project: string, page = 1) => apiFetch<Paged<ProjectPost>>(`${base}projects/${project}/posts/?page=${page}`),
  create: (project: string, data: unknown) => apiFetch<ProjectPost>(`${base}projects/${project}/posts/`, { method: "POST", ...jsonBody(data) }),
  update: (id: string, data: unknown) => apiFetch<ProjectPost>(`${base}posts/${id}/`, { method: "PATCH", ...jsonBody(data) }),
  replies: (id: string, page = 1) => apiFetch<Paged<PostReply>>(`${base}posts/${id}/replies/?page=${page}`),
  reply: (id: string, data: unknown) => apiFetch(`${base}posts/${id}/replies/`, { method: "POST", ...jsonBody(data) }),
  remove: (id: string, reply_id?: string) => apiFetch(`${base}posts/${id}/remove/`, { method: "POST", ...jsonBody({ reply_id: reply_id ?? null }) }),
  report: (id: string, reason: string, reply_id?: string) => apiFetch(`${base}posts/${id}/report/`, { method: "POST", ...jsonBody({ reason, reply_id: reply_id ?? null }) }),
  reports: (page = 1) => apiFetch<Paged<PostReport>>(`${base}admin/post-reports/?page=${page}`),
  moderate: (id: string, hide: boolean, reason: string) => apiFetch(`${base}admin/post-reports/${id}/resolve/`, { method: "POST", ...jsonBody({ hide, reason }) }),
};
