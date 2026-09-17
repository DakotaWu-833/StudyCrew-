import { apiFetch, apiFetchAll, jsonBody } from "./client";
import type {
  Comment,
  ExportJob,
  HolidayAdvisory,
  Insights,
  Invitation,
  Me,
  Meeting,
  Membership,
  Notification,
  Profile,
  Project,
  RSVP,
  Task,
  TaskPriority,
  TaskStatus,
  UUID,
} from "./types";

const query = (values: Record<string, string | undefined>) => {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => value && params.set(key, value));
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
};

export const accountApi = {
  me: () => apiFetch<Me>("/api/v1/me/"),
  updateProfile: (data: Partial<Profile>) =>
    apiFetch<Profile>("/api/v1/profile/", { method: "PATCH", ...jsonBody(data) }),
};

export const projectApi = {
  list: () => apiFetchAll<Project>("/api/v1/projects/"),
  listArchived: () => apiFetchAll<Project>("/api/v1/projects/?scope=archived"),
  listAll: () => apiFetchAll<Project>("/api/v1/projects/?scope=all"),
  get: (id: UUID) => apiFetch<Project>(`/api/v1/projects/${id}/`),
  create: (data: { name: string; description: string; due_at: string | null }) =>
    apiFetch<Project>("/api/v1/projects/", { method: "POST", ...jsonBody(data) }),
  update: (id: UUID, data: Partial<Pick<Project, "name" | "description" | "due_at">>) =>
    apiFetch<Project>(`/api/v1/projects/${id}/`, { method: "PATCH", ...jsonBody(data) }),
  archive: (id: UUID) => apiFetch<void>(`/api/v1/projects/${id}/`, { method: "DELETE" }),
  insights: (id: UUID, values: { range_start: string; range_end: string; event_type?: string }) =>
    apiFetch<Insights>(`/api/v1/projects/${id}/insights/${query(values)}`),
};

export const membershipApi = {
  list: (project: UUID) => apiFetchAll<Membership>(`/api/v1/memberships/${query({ project })}`),
  updateRole: (id: UUID, role: Membership["role"]) =>
    apiFetch<Membership>(`/api/v1/memberships/${id}/`, { method: "PATCH", ...jsonBody({ role }) }),
  remove: (id: UUID) => apiFetch<void>(`/api/v1/memberships/${id}/`, { method: "DELETE" }),
  transferOwnership: (id: UUID) =>
    apiFetch<Membership>(`/api/v1/memberships/${id}/transfer-ownership/`, {
      method: "POST",
      ...jsonBody({ previous_owner_role: "facilitator" }),
    }),
};

export const invitationApi = {
  listMine: () => apiFetchAll<Invitation>("/api/v1/invitations/"),
  listForProject: (project: UUID) =>
    apiFetchAll<Invitation>(`/api/v1/invitations/${query({ project })}`),
  create: (project: UUID, invited_email: string) =>
    apiFetch<Invitation>("/api/v1/invitations/", {
      method: "POST",
      ...jsonBody({ project, invited_email }),
    }),
  cancel: (id: UUID) => apiFetch<void>(`/api/v1/invitations/${id}/`, { method: "DELETE" }),
  accept: (id: UUID) => apiFetch<Project>(`/api/v1/invitations/${id}/accept/`, { method: "POST" }),
  decline: (id: UUID) => apiFetch<Invitation>(`/api/v1/invitations/${id}/decline/`, { method: "POST" }),
};

export interface TaskFilters {
  scope?: "active" | "archived" | "all";
  q?: string;
  status?: string;
  priority?: string;
  assignee?: string;
  due?: string;
}

export const taskApi = {
  list: (project: UUID, filters: TaskFilters = {}) =>
    apiFetchAll<Task>(`/api/v1/tasks/${query({ project, ...filters })}`),
  get: (id: UUID) => apiFetch<Task>(`/api/v1/tasks/${id}/`),
  create: (data: {
    project: UUID;
    title: string;
    description: string;
    priority: TaskPriority;
    due_at: string | null;
  }) => apiFetch<Task>("/api/v1/tasks/", { method: "POST", ...jsonBody(data) }),
  update: (id: UUID, data: Partial<Pick<Task, "title" | "description" | "priority" | "due_at">>) =>
    apiFetch<Task>(`/api/v1/tasks/${id}/`, { method: "PATCH", ...jsonBody(data) }),
  archive: (id: UUID) => apiFetch<void>(`/api/v1/tasks/${id}/`, { method: "DELETE" }),
  transition: (id: UUID, status: TaskStatus, blocker_note = "") =>
    apiFetch<Task>(`/api/v1/tasks/${id}/transition/`, {
      method: "POST",
      ...jsonBody({ status, blocker_note }),
    }),
  setAssignees: (id: UUID, assignee_ids: UUID[]) =>
    apiFetch<Task>(`/api/v1/tasks/${id}/assignees/`, {
      method: "PUT",
      ...jsonBody({ assignee_ids }),
    }),
};

export const commentApi = {
  list: (task: UUID) => apiFetchAll<Comment>(`/api/v1/comments/${query({ task })}`),
  create: (task: UUID, body: string, mentioned_user_ids: UUID[] = []) =>
    apiFetch<Comment>("/api/v1/comments/", {
      method: "POST",
      ...jsonBody({ task, body, mentioned_user_ids }),
    }),
  update: (id: UUID, body: string) =>
    apiFetch<Comment>(`/api/v1/comments/${id}/`, { method: "PATCH", ...jsonBody({ body }) }),
  remove: (id: UUID) => apiFetch<void>(`/api/v1/comments/${id}/`, { method: "DELETE" }),
  report: (id: UUID, reason: string, details: string) =>
    apiFetch<{ id: UUID; status: string }>(`/api/v1/comments/${id}/report/`, {
      method: "POST",
      ...jsonBody({ reason, details }),
    }),
};

export const meetingApi = {
  list: (project: UUID) => apiFetchAll<Meeting>(`/api/v1/meetings/${query({ project })}`),
  create: (data: {
    project: UUID;
    title: string;
    starts_at: string;
    ends_at: string;
    location: string;
    agenda: string;
  }) => apiFetch<Meeting>("/api/v1/meetings/", { method: "POST", ...jsonBody(data) }),
  update: (id: UUID, data: Partial<Pick<Meeting, "title" | "starts_at" | "ends_at" | "location" | "agenda">>) =>
    apiFetch<Meeting>(`/api/v1/meetings/${id}/`, { method: "PATCH", ...jsonBody(data) }),
  cancel: (id: UUID) => apiFetch<void>(`/api/v1/meetings/${id}/`, { method: "DELETE" }),
  rsvp: (id: UUID, response: RSVP, availability_note = "") =>
    apiFetch<Meeting>(`/api/v1/meetings/${id}/rsvp/`, {
      method: "PUT",
      ...jsonBody({ response, availability_note }),
    }),
  holiday: (id: UUID) => apiFetch<HolidayAdvisory>(`/api/v1/meetings/${id}/holiday/`),
};

export const notificationApi = {
  list: (unread = false) =>
    apiFetchAll<Notification>(`/api/v1/notifications/${query({ unread: unread ? "true" : undefined })}`),
  markRead: (id: UUID) =>
    apiFetch<Notification>(`/api/v1/notifications/${id}/read/`, { method: "PATCH", ...jsonBody({}) }),
};

export const exportApi = {
  list: () => apiFetchAll<ExportJob>("/api/v1/exports/"),
  create: (data: { project: UUID; format: "csv" | "pdf"; range_start: string; range_end: string }) =>
    apiFetch<ExportJob>("/api/v1/exports/", { method: "POST", ...jsonBody(data) }),
};
