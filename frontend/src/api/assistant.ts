import { apiFetch, jsonBody } from "./client";
import type { KnowledgeSource } from "./knowledge";

export interface AssistantSettings {
  available: boolean;
  notice: string;
  tools: string[];
  max_question_length: number;
  max_steps: number;
}

export interface AssistantSource extends Omit<KnowledgeSource, "kind"> {
  kind: "file" | "meeting" | "task";
}

export interface AssistantDraft {
  title: string;
  description: string;
  source_citations: string[];
  approval_token: string;
  can_create: boolean;
}

export interface AssistantTaskRequest {
  approval_token: string;
  title: string;
  description: string;
}

export interface AssistantCreatedTask {
  task_id: string;
  title: string;
  created: boolean;
  task_url: string;
}

export interface AssistantStep {
  tool: string;
  summary: string;
  result_count: number;
}

export interface AssistantResult {
  question: string;
  status: "completed" | "model_unavailable" | "no_evidence" | "invalid_response" | "limit_reached";
  answer: string | null;
  sources: AssistantSource[];
  drafts: AssistantDraft[];
  steps: AssistantStep[];
  warnings: string[];
  model: string | null;
}

const projectPath = (project: string) => `/api/v1/knowledge/projects/${encodeURIComponent(project)}/assistant/`;
export const assistantApi = {
  settings: (project: string, signal?: AbortSignal) => apiFetch<AssistantSettings>(projectPath(project), { signal, cache: "no-store" }),
  run: (project: string, question: { question: string }, signal?: AbortSignal) => apiFetch<AssistantResult>(projectPath(project), { method: "POST", ...jsonBody(question), signal, cache: "no-store" }),
  createTask: (project: string, request: AssistantTaskRequest, signal?: AbortSignal) => apiFetch<AssistantCreatedTask>(`${projectPath(project)}tasks/`, { method: "POST", ...jsonBody(request), signal, cache: "no-store" }),
};
