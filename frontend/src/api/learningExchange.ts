import { apiFetch, jsonBody } from "./client";

export interface LearningBatch { id: string; source: string; source_namespace: string; timezone_name: string; created_at: string; imported_count: number; skipped_count: number; }
export interface LearningOverview {
  project: { id: string; name: string; archived_at: string | null; can_import: boolean };
  timezone_name: string; batches: LearningBatch[]; page: number; pages: number; total: number;
}
export interface LearningRow { row: number; source_id: string; title: string; description: string; priority: string; official_due_at: string | null; errors: string[]; action: "create" | "skip"; existing_task: string | null; }
export interface LearningPreview {
  valid: boolean; preview_id: string | null; expires_at: string | null; timezone_name: string;
  source: string; source_namespace: string; rows: LearningRow[]; ignored_columns: string[]; create_count: number; skip_count: number;
}
const base = "/api/v1/learning-exchange/";
export const learningExchangeApi = {
  overview: (project: string, page = 1) => apiFetch<LearningOverview>(`${base}projects/${project}/?page=${page}`),
  preview: (project: string, data: FormData) => apiFetch<LearningPreview>(`${base}projects/${project}/preview/`, { method: "POST", body: data }),
  confirm: (project: string, preview: string) => apiFetch<{ batch: LearningBatch; replayed: boolean }>(`${base}projects/${project}/import/`, { method: "POST", ...jsonBody({ preview_id: preview, confirmed: true }) }),
  sampleUrl: `${base}sample/`,
  exportUrl: (project: string, batch?: string) => `${base}projects/${project}/${batch ? `batches/${batch}/` : ""}export/`,
};
