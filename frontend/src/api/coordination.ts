import { apiFetch, jsonBody } from "./client";
import type { UserSummary } from "./types";

const base = "/api/v1/coordination";
const query = (data: Record<string, string | undefined>) => {
  const params = new URLSearchParams();
  Object.entries(data).forEach(([key, value]) => { if (value) params.set(key, value); });
  return params.toString();
};
const post = <T>(path: string, data: unknown = {}) => apiFetch<T>(`${base}${path}`, { method: "POST", ...jsonBody(data) });

export interface CalendarEvent {
  id: string; kind: "meeting" | "task" | "task_official" | "project" | "submission_internal" | "submission_official" | "milestone"; title: string;
  project_id: string; project_name: string; starts_at: string; ends_at: string;
  cancelled: boolean; location: string; description: string; updated_at: string; url: string;
}
export interface CalendarData { range_start: string; range_end: string; time_zone: string; events: CalendarEvent[]; truncated: boolean; }
export interface CoordinationPagination { page: number; pages: number; count: number; }
export interface CalendarSubscription { id: string; project_id: string | null; include_details: boolean; revoked_at: string | null; expires_at: string; created_at: string; feed_url?: string; }
export interface AvailabilitySlot { weekday: number; start_minute: number; end_minute: number; }
export interface AvailabilityData {
  week_start: string; time_zone: string; basis: string;
  members: (UserSummary & { role: string; shared_availability: boolean })[];
  mine: { slots: AvailabilitySlot[]; time_zone: string };
  cells: { weekday: number; start_minute: number; starts_at: string; available_ids: string[]; available_count: number }[];
}
export interface Participant { user_id: string; required: boolean; display_name?: string; active?: boolean; }
export interface SchedulingPoll {
  id: string; title: string; agenda: string; location: string; closed_at: string | null; meeting_id: string | null;
  can_manage: boolean; can_vote: boolean; participants: Participant[];
  options: { id: string; starts_at: string; ends_at: string; votes: { user_id: string; response: "yes" | "maybe" | "no" }[] }[];
}
export interface MeetingRecord {
  id: string; title: string; starts_at: string; ends_at: string;
  lifecycle_state: "scheduled" | "ended" | "cancelled" | "archived";
  can_manage: boolean; can_record: boolean; participants: Participant[]; record_id: string | null;
  minutes: string; decisions: string; version: number;
  confirmations: { user: UserSummary; version: number; current: boolean; updated_at: string }[];
  attendance: { user: UserSummary; attended: boolean; note: string; recorded_by: UserSummary; updated_at: string }[];
  actions: { task_id: string; title: string; status: string; due_at: string | null }[];
  history: { id: string; kind: string; actor: UserSummary; metadata: Record<string, unknown>; created_at: string }[];
}
export interface TeamEvidenceMember extends UserSummary { role: string; active: boolean; joined_at: string; removed_at: string | null; recorded_attendance: number; system_events: number; tasks_marked_done: number; comments_created: number; accepted_rsvps: number; }
export interface ContributionClaim {
  id: string; author: UserSummary; title: string; statement: string; artifact_url: string;
  task_id: string | null; task_title: string; supersedes_id: string | null; created_at: string;
  status: "withdrawn" | "superseded" | "awaiting_collaborators" | "team_confirmed" | "changes_requested" | "self_reported";
  can_review: boolean; can_respond: boolean; can_withdraw: boolean; can_revise: boolean;
  contributors: { user: UserSummary; response: "pending" | "confirmed" | "declined" }[];
  reviews: { reviewer: UserSummary; outcome: string; note: string; created_at: string }[];
}
export interface EvidenceData extends CoordinationPagination { range_start: string; range_end: string; claims: ContributionClaim[]; truncated: boolean; members: TeamEvidenceMember[]; basis: string; }

export const coordinationApi = {
  calendar: (start: string, end: string, project?: string) => apiFetch<CalendarData>(`${base}/calendar/?${query({ range_start: start, range_end: end, project })}`),
  calendarExportUrl: (start: string, end: string, project?: string) => `${base}/calendar/export/?${query({ range_start: start, range_end: end, project })}`,
  subscriptions: () => apiFetch<{ subscriptions: CalendarSubscription[] }>(`${base}/subscriptions/`),
  subscribe: (project: string | undefined, include_details: boolean) => post<CalendarSubscription>("/subscriptions/", { project: project || null, include_details }),
  rotateSubscription: (id: string) => post<CalendarSubscription>(`/subscriptions/${id}/rotate/`),
  revokeSubscription: (id: string) => post<CalendarSubscription>(`/subscriptions/${id}/revoke/`),
  availability: (project: string, week: string) => apiFetch<AvailabilityData>(`${base}/availability/?${query({ project, week_start: week })}`),
  saveAvailability: (project: string, time_zone: string, slots: AvailabilitySlot[]) => apiFetch<unknown>(`${base}/availability/`, { method: "PUT", ...jsonBody({ project, time_zone, slots }) }),
  polls: (project: string, page = 1) => apiFetch<CoordinationPagination & { polls: SchedulingPoll[]; truncated: boolean }>(`${base}/polls/?${query({ project, page: String(page) })}`),
  createPoll: (data: { project: string; title: string; agenda: string; location: string; participants: Participant[]; options: { starts_at: string; ends_at: string }[] }) => post<SchedulingPoll>("/polls/", data),
  vote: (option: string, response: "yes" | "maybe" | "no") => post<SchedulingPoll>(`/poll-options/${option}/vote/`, { response }),
  closePoll: (poll: string, option_id: string) => post<MeetingRecord>(`/polls/${poll}/close/`, { option_id }),
  cancelPoll: (poll: string) => post<SchedulingPoll>(`/polls/${poll}/cancel/`),
  meetingRecords: (project: string, page = 1) => apiFetch<CoordinationPagination & { meetings: MeetingRecord[]; truncated: boolean; members: (UserSummary & { active: boolean })[] }>(`${base}/meeting-records/?${query({ project, page: String(page) })}`),
  meetingRecord: (meeting: string) => apiFetch<MeetingRecord>(`${base}/meeting-records/${meeting}/`),
  saveRecord: (meeting: string, data: { participants?: Participant[]; minutes?: string; decisions?: string; expected_version?: number }) => apiFetch<MeetingRecord>(`${base}/meeting-records/${meeting}/`, { method: "PUT", ...jsonBody(data) }),
  confirmMinutes: (meeting: string, version: number) => post<MeetingRecord>(`/meeting-records/${meeting}/confirm/`, { version }),
  attendance: (meeting: string, user_id: string, attended: boolean, note: string) => post<MeetingRecord>(`/meeting-records/${meeting}/attendance/`, { user_id, attended, note }),
  action: (meeting: string, data: { title: string; description: string; due_at: string | null; assignee_ids: string[] }) => post<MeetingRecord>(`/meeting-records/${meeting}/actions/`, data),
  repeat: (meeting: string, count: number, interval_days: number, time_zone: string) => post<{ occurrence_ids: string[] }>(`/meeting-records/${meeting}/repeat/`, { count, interval_days, time_zone }),
  evidence: (project: string, range_start?: string, range_end?: string, page = 1) => apiFetch<EvidenceData>(`${base}/claims/?${query({ project, range_start, range_end, page: String(page) })}`),
  claim: (data: { project: string; title: string; statement: string; artifact_url: string; task_id: string | null; contributor_ids: string[]; supersedes_id: string | null }) => post<{ id: string }>("/claims/", data),
  respondClaim: (id: string, response: "confirmed" | "declined") => post<{ id: string }>(`/claims/${id}/respond/`, { response }),
  reviewClaim: (id: string, outcome: "confirmed" | "changes_requested", note: string) => post<{ id: string }>(`/claims/${id}/review/`, { outcome, note }),
  withdrawClaim: (id: string) => post<{ id: string }>(`/claims/${id}/withdraw/`),
};
