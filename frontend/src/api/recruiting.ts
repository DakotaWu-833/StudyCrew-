import { apiFetch, jsonBody } from "./client";

export interface RecruitingPerson { id: string; display_name: string }
export interface RecruitingApplication {
  id: string; status: string; message: string; reason?: string; created_at: string;
  applicant?: RecruitingPerson; listing?: { id: string; title: string }; joined_project?: string | null;
}
export interface RecruitingListing {
  id: string; title: string; university: string; course: string; term: string; description: string;
  skills: string[]; languages: string[]; cooperation: string; capacity: number; remaining: number;
  expires_at: string; status: string; owner: RecruitingPerson; student_status: "self_reported";
  bookmarked: boolean; is_owner: boolean; my_application: RecruitingApplication | null;
  joined_project?: string | null; project?: string; updated_at: string;
}
export interface RecruitingPage<T> { results: T[]; count: number; page: number; pages: number }
export interface RecruitingRecommendation extends RecruitingListing {
  match_reasons: { kind: "course" | "skills" | "languages" | "cooperation"; values: string[]; text: string }[];
}
export interface RecruitingRecommendations extends RecruitingPage<RecruitingRecommendation> {
  preferences: { courses: { code: string; university: string }[]; skills: string[]; languages: string[]; cooperation: string; overrides: string[]; missing_fields: string[] };
  examined_count: number; eligible_count: number; candidate_window: number; limited: boolean; ordering: string;
}
export interface RecruitingOverview {
  managed_projects: { id: string; name: string }[]; mine: RecruitingListing[]; applications: RecruitingApplication[];
  mine_pagination: Omit<RecruitingPage<never>, "results">;
  applications_pagination: Omit<RecruitingPage<never>, "results">;
  projects_pagination: Omit<RecruitingPage<never>, "results">;
}
export interface RecruitingReport {
  id: string; listing: { id: string; title: string; hidden_at?: string | null }; reason: string; details: string; status: string;
  reported_by: RecruitingPerson; created_at: string;
}
const base = "/api/v1/recruiting/";
export const recruitingApi = {
  recommendations: (preferences: Record<string, string> = {}, page = 1) => apiFetch<RecruitingRecommendations>(`${base}recommendations/?${new URLSearchParams({ ...preferences, page: String(page) })}`),
  list: (filters: Record<string, string>, page = 1) => apiFetch<RecruitingPage<RecruitingListing>>(`${base}listings/?${new URLSearchParams({ ...filters, page: String(page) })}`),
  overview: (minePage = 1, applicationsPage = 1, projectsPage = 1) => apiFetch<RecruitingOverview>(`${base}overview/?${new URLSearchParams({ mine_page: String(minePage), applications_page: String(applicationsPage), projects_page: String(projectsPage) })}`),
  detail: (id: string) => apiFetch<RecruitingListing>(`${base}listings/${id}/`),
  create: (data: unknown) => apiFetch<RecruitingListing>(`${base}listings/`, { method: "POST", ...jsonBody(data) }),
  update: (id: string, data: unknown) => apiFetch<RecruitingListing>(`${base}listings/${id}/`, { method: "PATCH", ...jsonBody(data) }),
  listingAction: <T = RecruitingListing>(id: string, action: string, data: unknown = {}, method = "POST") => apiFetch<T>(`${base}listings/${id}/${action}/`, { method, ...jsonBody(data) }),
  applications: (id: string, page = 1) => apiFetch<RecruitingPage<RecruitingApplication>>(`${base}listings/${id}/applications/?page=${page}`),
  decide: (id: string, decision: "approve" | "reject", reason: string) => apiFetch<RecruitingApplication>(`${base}applications/${id}/decision/`, { method: "POST", ...jsonBody({ decision, reason }) }),
  withdraw: (id: string) => apiFetch<RecruitingApplication>(`${base}applications/${id}/withdraw/`, { method: "POST", ...jsonBody({}) }),
  reports: (page = 1) => apiFetch<RecruitingPage<RecruitingReport>>(`${base}reports/?page=${page}`),
  resolveReport: (id: string, decision: "dismiss" | "hide" | "restore", reason: string) => apiFetch<RecruitingReport>(`${base}reports/${id}/resolve/`, { method: "POST", ...jsonBody({ decision, reason }) }),
};
