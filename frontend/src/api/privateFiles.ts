import { apiFetch, apiFetchBlob, jsonBody } from "./client";

export interface FileVersion {
  id: string; number: number; filename: string; content_type: string; size: number;
  sha256: string; scan_status: string; created_at: string; download_url: string;
  preview_kind?: "text" | "image" | "pdf" | null; preview_url?: string | null;
}
export interface TrashDocument extends Omit<ProjectDocument, "latest"> {
  latest: null; removed_at: string; purge_after: string; can_restore: boolean;
}
export interface TrashPage { results: TrashDocument[]; count: number; page: number; pages: number; retention_days: number }
export interface FileDiff {
  from_version: string; to_version: string; identical: boolean; truncated: boolean; line_ending_changed?: boolean;
  lines: { kind: "header" | "added" | "removed" | "context"; text: string; no_final_newline?: boolean }[];
}
export interface ProjectDocument {
  id: string; project: string; title: string; folder: string; tags: string[]; pinned: boolean;
  author: { id: string; display_name: string }; revision: number; created_at: string; updated_at: string;
  can_edit: boolean; latest: FileVersion; versions: FileVersion[];
}
export interface FilePage {
  results: ProjectDocument[]; count: number; page: number; pages: number;
  usage: { bytes: number; limit: number; file_limit: number; daily_bytes_limit: number; daily_upload_limit: number };
  allowed_extensions: string[]; scan_required: boolean;
}
const base = "/api/v1/files/projects/";
const documentPath = (project: string, id: string) => `${base}${project}/documents/${id}/`;
export const privateFilesApi = {
  list: (project: string, q = "", folder = "", tag = "", page = 1) => apiFetch<FilePage>(`${base}${project}/?${new URLSearchParams({ q, folder, tag, page: String(page) })}`),
  upload: (project: string, data: FormData) => apiFetch<ProjectDocument>(`${base}${project}/`, { method: "POST", body: data }),
  detail: (project: string, id: string) => apiFetch<ProjectDocument>(documentPath(project, id)),
  update: (project: string, id: string, data: unknown) => apiFetch<ProjectDocument>(documentPath(project, id), { method: "PATCH", ...jsonBody(data) }),
  remove: (project: string, id: string, revision: number) => apiFetch<void>(documentPath(project, id), { method: "DELETE", ...jsonBody({ expected_revision: revision }) }),
  version: (project: string, id: string, data: FormData) => apiFetch<ProjectDocument>(`${documentPath(project, id)}versions/`, { method: "POST", body: data }),
  trash: (project: string, q = "", page = 1) => apiFetch<TrashPage>(`${base}${project}/trash/?${new URLSearchParams({ q, page: String(page) })}`),
  restore: (project: string, id: string, revision: number) => apiFetch<ProjectDocument>(`${documentPath(project, id)}restore/`, { method: "POST", ...jsonBody({ expected_revision: revision }) }),
  preview: (project: string, id: string, version: string) => apiFetchBlob(`${documentPath(project, id)}preview/?${new URLSearchParams({ version })}`),
  compare: (project: string, id: string, from: string, to: string) => apiFetch<FileDiff>(`${documentPath(project, id)}compare/?${new URLSearchParams({ from_version: from, to_version: to })}`),
};
