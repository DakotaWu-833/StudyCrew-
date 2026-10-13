import { apiFetch, jsonBody } from "./client";

export interface RecurringSchedule {
  id: string; author_id: string; frequency: "weekly" | "monthly"; interval: number;
  timezone_name: string; start_local: string; until_date: string; occurrence_limit: number;
  lead_days: number; generated_count: number; next_run_at: string | null; next_due_at: string | null;
  stopped_at: string | null; stop_reason: string; updated_at: string; can_stop?: boolean;
}
export interface TimeEntry {
  id: string; started_at: string; ended_at: string | null; seconds: number; source: "timer" | "manual";
  note: string; cancelled_at: string | null; corrected_at: string | null; capped: boolean; updated_at: string;
}
export interface ActiveTimer {
  id: string; started_at: string; accessible: boolean; task_id: string | null;
  project_id: string | null; title: string | null; read_only: boolean;
}
export interface ProductivityOverview {
  schedules: RecurringSchedule[]; entries: TimeEntry[]; page: number; pages: number; total: number;
  active_timer: ActiveTimer | null; actual_seconds: number; my_seconds: number;
  timezone_name: string; read_only: boolean; can_stop_schedules: boolean;
}
export interface ScheduleInput {
  frequency: "weekly" | "monthly"; interval: number; timezone_name: string; start_local: string;
  until_date: string; occurrence_limit: number; lead_days: number;
}
export interface ManualTimeInput { started_at: string; minutes: number; note: string; }
export interface DueBuckets { overdue: number; next_7_days: number; later: number; no_deadline: number; }
export interface Workload {
  project: { id: string; name: string }; as_of: string; actual_seconds: number; method: string;
  members: { user_id: string; name: string; current_member: boolean; open_tasks: number; assigned_estimate_hours: string; actual_seconds: number; due: DueBuckets }[];
  unassigned: { open_tasks: number; estimate_hours: string; due: DueBuckets };
}
const base = "/api/v1/productivity/";
const taskPath = (project: string, task: string) => `${base}projects/${project}/tasks/${task}/`;
const post = <T>(path: string, data?: unknown) => apiFetch<T>(path, { method: "POST", ...(data ? jsonBody(data) : {}) });
export const productivityApi = {
  overview: (project: string, task: string, page = 1) => apiFetch<ProductivityOverview>(`${taskPath(project, task)}?page=${page}`),
  createSchedule: (project: string, task: string, data: ScheduleInput) => post<RecurringSchedule>(`${taskPath(project, task)}schedules/`, data),
  stopSchedule: (project: string, task: string, id: string) => post<RecurringSchedule>(`${taskPath(project, task)}schedules/${id}/stop/`),
  startTimer: (project: string, task: string) => post<TimeEntry>(`${taskPath(project, task)}timer/start/`),
  stopTimer: (project: string, task: string, note: string) => post<TimeEntry>(`${taskPath(project, task)}timer/stop/`, { note }),
  activeTimer: () => apiFetch<{ active_timer: ActiveTimer | null }>(`${base}timer/`),
  discardTimer: () => post<{ discarded: boolean }>(`${base}timer/discard/`),
  addManual: (project: string, task: string, data: ManualTimeInput) => post<TimeEntry>(`${taskPath(project, task)}time/`, data),
  correct: (project: string, task: string, entry: TimeEntry, data: ManualTimeInput) => apiFetch<TimeEntry>(`${taskPath(project, task)}time/${entry.id}/`, { method: "PATCH", ...jsonBody({ ...data, expected_updated_at: entry.updated_at }) }),
  discard: (project: string, task: string, entry: TimeEntry) => post<{ discarded: boolean }>(`${taskPath(project, task)}time/${entry.id}/discard/`, { expected_updated_at: entry.updated_at }),
  workload: (project: string) => apiFetch<Workload>(`${base}projects/${project}/workload/`),
};
