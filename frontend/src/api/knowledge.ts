import { apiFetch, jsonBody } from "./client";

export interface KnowledgeSettings {
  generation_available: boolean;
  provider: "disabled" | "ollama" | "compatible";
  source_types: string[];
  supported_files: string[];
  max_question_length: number;
  retrieval: "bm25";
  notice: string;
}

export interface KnowledgeSource {
  citation: string;
  kind: "file" | "meeting";
  source_id: string;
  title: string;
  version: number | null;
  page: number | null;
  excerpt: string;
  url: string;
  locator: string;
}

export interface KnowledgeSearch {
  question: string;
  sources: KnowledgeSource[];
  warnings: string[];
  retrieval: "bm25";
  limited: boolean;
}

export interface KnowledgeAnswer extends KnowledgeSearch {
  answer: string | null;
  status: "answered" | "no_evidence" | "model_unavailable" | "unverified_answer";
  model: string | null;
}

export interface KnowledgeQuestion {
  question: string;
  max_sources?: number;
}

const projectPath = (project: string) => `/api/v1/knowledge/projects/${encodeURIComponent(project)}/`;
export const knowledgeApi = {
  settings: (project: string, signal?: AbortSignal) => apiFetch<KnowledgeSettings>(projectPath(project), { signal, cache: "no-store" }),
  search: (project: string, question: KnowledgeQuestion, signal?: AbortSignal) => apiFetch<KnowledgeSearch>(`${projectPath(project)}search/`, { method: "POST", ...jsonBody(question), signal, cache: "no-store" }),
  ask: (project: string, question: KnowledgeQuestion, signal?: AbortSignal) => apiFetch<KnowledgeAnswer>(`${projectPath(project)}ask/`, { method: "POST", ...jsonBody(question), signal, cache: "no-store" }),
};
