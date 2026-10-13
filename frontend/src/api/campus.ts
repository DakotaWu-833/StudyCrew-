import { apiFetch, jsonBody } from "./client";
import type { UUID } from "./types";

export interface AcademicTerm { id: UUID; university: string; year: number; name: string; archived_at: string | null; }
export interface AcademicCourse { id: UUID; university: string; code: string; name: string; }
export interface CourseLink { id: UUID; project: UUID; course: AcademicCourse; term: AcademicTerm; }
export interface AcademicPerson { id: UUID; display_name: string; role?: string; }
export interface CheckItem { id: UUID; text: string; checked: boolean; }
export interface Pagination { total: number; page: number; page_size: number; pages: number; }
export interface CampusPageResult<T> extends Pagination { results: T[]; }
export interface AcademicTask {
  id: UUID; project: UUID; project_name: string; title: string; description: string; status: string; priority: string;
  internal_due_at: string | null; official_due_at: string | null; acceptance: string; outcome_url: string;
  parent: UUID | null; milestone: UUID | null; reviewer: UUID | null; review_state: string; review_note: string;
  tags?: string[]; estimate_hours?: string | null; reviewed_at: string | null; dependencies: UUID[]; checklist: CheckItem[]; assignees: AcademicPerson[];
}
export interface Milestone { id: UUID; title: string; due_at: string | null; done: boolean; }
export interface Confirmation { user: UUID; revision: number; confirmed_at: string; }
export interface Resource {
  id: UUID; project: UUID; project_name: string; title: string; url: string; description: string;
  tags: string[]; pinned: boolean; added_by: AcademicPerson; can_edit: boolean; created_at: string;
}
export interface CampusOverview {
  terms: AcademicTerm[]; courses: AcademicCourse[]; links: CourseLink[];
  templates: { key: string; name: string; task_count: number }[];
  join_requests: { id: UUID; status: string; created_at: string; project: UUID | null }[];
}
export interface ProjectPlan {
  risks?: { unassigned: number; overdue: number; blocked: number; open_dependencies: number; blocked_tasks: { id: string; title: string; since: string }[] };
  project: { id: UUID; name: string; archived_at: string | null; role: string };
  current_user: UUID; members: AcademicPerson[]; tasks: AcademicTask[]; milestones: Milestone[]; course_links: CourseLink[];
  task_pagination: Pagination;
  task_choices: { id: UUID; title: string; status: string }[];
  agreement: { body: string; revision: number; confirmations: Confirmation[] } | null;
  submission: {
    official_due_at: string | null; internal_due_at: string | null; revision: number; items: CheckItem[];
    confirmations: Confirmation[]; receipt_url: string; receipt_reference: string; submitted_at: string | null; submitted_by: UUID | null;
  } | null;
}
export interface SearchResults {
  meetings?: {id: string; project: string; title: string}[]; minutes?: {id: string; project: string; title: string; excerpt: string}[]; comments?: {id: string; project: string; task: string; title: string; excerpt: string}[]; discussions?: {id: string; project: string; title: string}[]; replies?: {id: string; project: string; title: string; excerpt: string}[]; page?: number; pages?: number; total?: number; projects: { id: UUID; name: string }[]; tasks: AcademicTask[]; resources: Resource[]; }
export interface JoinManagement {
  links: { id: UUID; expires_at: string; max_uses: number; uses: number; revoked_at: string | null }[];
  requests: { id: UUID; user: AcademicPerson; status: string; created_at: string }[];
}

const base = "/api/v1/campus/";
export const campusApi = {
  overview: () => apiFetch<CampusOverview>(`${base}overview/`),
  todos: (due = "open", q = "", page = 1) => apiFetch<CampusPageResult<AcademicTask>>(`${base}todos/?${new URLSearchParams({ due, q, page: String(page) })}`),
  search: (q: string, page = 1) => apiFetch<SearchResults>(`${base}search/?${new URLSearchParams({ q, page: String(page) })}`),
  plan: (project: UUID, page = 1) => apiFetch<ProjectPlan>(`${base}projects/${project}/?${new URLSearchParams({ page: String(page) })}`),
  resources: (project: UUID, q = "", tag = "", page = 1) => apiFetch<CampusPageResult<Resource>>(`${base}projects/${project}/resources/?${new URLSearchParams({ q, tag, page: String(page) })}`),
  joins: (project: UUID) => apiFetch<JoinManagement>(`${base}projects/${project}/join-links/`),
  action: <T = { saved?: boolean }>(path: string, data: unknown = {}, method = "POST") => apiFetch<T>(`${base}${path}`, { method, ...jsonBody(data) }),
  projectAction: <T = { saved?: boolean }>(project: UUID, path: string, data: unknown = {}, method = "POST") => apiFetch<T>(`${base}projects/${project}/${path}`, { method, ...jsonBody(data) }),
};
