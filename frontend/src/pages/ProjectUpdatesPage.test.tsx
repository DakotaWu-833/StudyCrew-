import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import ProjectUpdatesPage from "./ProjectUpdatesPage";
import { discussionsApi } from "../api/discussions";
vi.mock("../api/discussions", () => ({ discussionsApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), reply: vi.fn(), remove: vi.fn(), report: vi.fn() } }));
vi.mock("../api/resources", () => ({ accountApi: { me: vi.fn() }, membershipApi: { list: vi.fn() }, projectApi: { get: vi.fn() } }));
let root: Root, container: HTMLDivElement, cache: QueryClient;
beforeEach(() => { Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); vi.clearAllMocks(); vi.mocked(discussionsApi.list).mockResolvedValue({ results: [] } as never); container = document.createElement("div"); document.body.append(container); root = createRoot(container); cache = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } }); cache.setQueryData(["me"], { user: { id: "owner" } }); cache.setQueryData(["project", "team"], { id: "team", current_user_role: "owner", archived_at: null }); cache.setQueryData(["memberships", "team"], { results: [{ user: { id: "member", display_name: "Teammate" } }] }); cache.setQueryData(["project-posts", "team", 1], { results: [] }); });
afterEach(async () => { await act(async () => root.unmount()); cache.clear(); container.remove(); localStorage.clear(); });
async function render() { await act(async () => root.render(<QueryClientProvider client={cache}><MemoryRouter initialEntries={["/projects/team/updates"]}><Routes><Route path="/projects/:projectId/updates" element={<ProjectUpdatesPage />} /></Routes></MemoryRouter></QueryClientProvider>)); }
it("submits a pinned announcement with explicit teammate mentions and resets only after success", async () => {
  vi.mocked(discussionsApi.create).mockResolvedValue({} as never); await render(); const form = container.querySelector("form")!;
  form.querySelector<HTMLInputElement>('[name="title"]')!.value = "Review decision"; form.querySelector<HTMLTextAreaElement>('[name="body"]')!.value = "Please review the final draft.";
  form.querySelector<HTMLSelectElement>('[name="kind"]')!.value = "announcement"; form.querySelector<HTMLInputElement>('[name="pinned"]')!.checked = true;
  form.querySelector<HTMLOptionElement>('[name="mention_ids"] option')!.selected = true;
  await act(async () => { form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); await new Promise(resolve => setTimeout(resolve, 25)); });
  expect(discussionsApi.create).toHaveBeenCalledWith("team", { title: "Review decision", body: "Please review the final draft.", kind: "announcement", pinned: true, mention_ids: ["member"] });
  expect(form.querySelector<HTMLInputElement>('[name="title"]')!.value).toBe("");
});
it("shows archived discussions as read-only", async () => {
  cache.setQueryData(["project", "team"], { id: "team", current_user_role: "member", archived_at: "2026-10-01" }); await render();
  expect(container.textContent).not.toContain("Start a discussion"); expect(container.querySelector("textarea")).toBeNull();
});
