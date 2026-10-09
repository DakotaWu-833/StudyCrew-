import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import TeamFinderPage from "./TeamFinderPage";
import ProjectFilesPage from "./ProjectFilesPage";
import { recruitingApi } from "../api/recruiting";
import { privateFilesApi, type ProjectDocument } from "../api/privateFiles";
import { APIError } from "../api/client";

vi.mock("../api/recruiting", () => ({ recruitingApi: Object.fromEntries(["list", "overview", "detail", "create", "update", "listingAction", "applications", "decide", "withdraw", "reports", "resolveReport"].map(name => [name, vi.fn()])) }));
vi.mock("../api/privateFiles", () => ({ privateFilesApi: Object.fromEntries(["list", "upload", "detail", "update", "remove", "version"].map(name => [name, vi.fn()])) }));
vi.mock("../api/resources", () => ({ accountApi: { me: vi.fn() }, projectApi: { get: vi.fn() } }));

let container: HTMLDivElement, root: Root, cache: QueryClient;
const expiry = "2026-11-01T23:59:59Z";
const version = { id: "v1", number: 1, filename: "brief.txt", content_type: "text/plain", size: 100, sha256: "a".repeat(64), scan_status: "local_unscanned", created_at: "2026-10-02T01:00:00Z", download_url: "/download/brief" };
const doc: ProjectDocument = { id: "doc", project: "team", title: "Assignment brief", folder: "Briefs", tags: ["brief"], pinned: false, author: { id: "owner", display_name: "Owner" }, revision: 4, created_at: "2026-10-02", updated_at: "2026-10-02", can_edit: true, latest: version, versions: [version] };
const listing = { id: "opening", title: "Research team", university: "University", course: "COMP", term: "Semester 2", description: "A research project", skills: ["Python"], languages: ["English"], cooperation: "hybrid", capacity: 3, remaining: 3, expires_at: expiry, status: "open", owner: { id: "owner", display_name: "Owner" }, student_status: "self_reported", bookmarked: false, is_owner: false, my_application: null, updated_at: "2026-10-02T01:00:00Z" };
const overview = { projects_pagination: { count: 1, page: 1, pages: 1 }, managed_projects: [{ id: "team", name: "Private team" }], mine: [], applications: [], mine_pagination: { count: 0, page: 1, pages: 1 }, applications_pagination: { count: 0, page: 1, pages: 1 } };
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.clearAllMocks(); container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  cache = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
  cache.setQueryData(["me"], { user: { id: "owner" }, permissions: { site_moderator: false } });
  cache.setQueryData(["project", "team"], { id: "team", current_user_role: "owner", archived_at: null });
  cache.setQueryData(["recruiting-overview", 1, 1, 1], overview);
  cache.setQueryData(["recruiting-listings", {}, 1], { results: [listing], count: 1, page: 1, pages: 1 });
  cache.setQueryData(["private-files", "team", "", "", "", 1], { results: [doc], count: 1, page: 1, pages: 1, usage: { bytes: 100, limit: 250 * 1024 * 1024, file_limit: 10 * 1024 * 1024 }, allowed_extensions: ["txt"], scan_required: false });
  vi.mocked(recruitingApi.overview).mockResolvedValue(overview);
  vi.mocked(recruitingApi.list).mockResolvedValue({ results: [listing], count: 1, page: 1, pages: 1 } as never);
  vi.mocked(privateFilesApi.list).mockResolvedValue(cache.getQueryData(["private-files", "team", "", "", "", 1]) as never);
});
afterEach(async () => { await act(async () => root.unmount()); cache.clear(); container.remove(); });
async function renderTeam(path = "/find-team") { await act(async () => root.render(<QueryClientProvider client={cache}><MemoryRouter initialEntries={[path]}><TeamFinderPage /></MemoryRouter></QueryClientProvider>)); }
async function renderFiles() { await act(async () => root.render(<QueryClientProvider client={cache}><MemoryRouter initialEntries={["/projects/team/files"]}><Routes><Route path="/projects/:projectId/files" element={<ProjectFilesPage />} /></Routes></MemoryRouter></QueryClientProvider>)); }
async function click(name: string) { const button = Array.from(container.querySelectorAll("button")).find(item => item.textContent === name); if (!button) throw new Error("Missing button "+name); await act(async () => { button.click(); await new Promise(resolve => setTimeout(resolve, 25)); }); }
async function submit(form: HTMLFormElement) { await act(async () => { form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); await new Promise(resolve => setTimeout(resolve, 25)); }); }

it("publishes only the selected opening details after explicit consent", async () => {
  vi.mocked(recruitingApi.create).mockResolvedValue({ ...listing, is_owner: true } as never);
  vi.mocked(recruitingApi.detail).mockResolvedValue({ ...listing, is_owner: true } as never);
  vi.mocked(recruitingApi.applications).mockResolvedValue({ results: [], count: 0, page: 1, pages: 1 });
  await renderTeam(); await click("Publish a team opening");
  const form = container.querySelector<HTMLSelectElement>('[name="project"]')!.closest("form")!;
  for (const [name, value] of Object.entries({ project: "team", title: "Study group", university: "University", course: "COMP", term: "Semester 2", description: "Build a project together", skills: "Python, Writing", languages: "English", expires: "2026-11-01" })) form.querySelector<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(`[name="${name}"]`)!.value = value;
  form.querySelector<HTMLInputElement>('[name="publish_consent"]')!.checked = true;
  await submit(form);
  expect(recruitingApi.create).toHaveBeenCalledWith(expect.objectContaining({ project: "team", title: "Study group", skills: ["Python", "Writing"], publish_consent: true }));
  expect(container.textContent).toContain("Recruiting updated.");
});
it("submits an application without automatically granting project membership", async () => {
  cache.setQueryData(["recruiting-detail", "opening"], listing);
  vi.mocked(recruitingApi.listingAction).mockResolvedValue({} as never);
  vi.mocked(recruitingApi.detail).mockResolvedValue(listing as never);
  await renderTeam("/find-team?listing=opening");
  const message = container.querySelector<HTMLTextAreaElement>('[name="message"]')!; message.value = "I can help with Python and meet on Mondays.";
  await submit(message.closest("form")!);
  expect(recruitingApi.listingAction).toHaveBeenCalledWith("opening", "apply", { message: message.value || "I can help with Python and meet on Mondays." });
  expect(recruitingApi.decide).not.toHaveBeenCalled();
  expect(container.textContent).not.toContain("Open private project");
});
it("shows a pending application with withdrawal instead of another apply form", async () => {
  cache.setQueryData(["recruiting-detail", "opening"], { ...listing, my_application: { id: "application", status: "pending" } });
  await renderTeam("/find-team?listing=opening");
  expect(container.textContent).toContain("Withdraw application");
  expect(container.querySelector('[name="message"]')).toBeNull();
});
it("reports a stale opening edit as an error and keeps editing available", async () => {
  cache.setQueryData(["recruiting-detail", "opening"], { ...listing, is_owner: true, project: "team" });
  cache.setQueryData(["recruiting-applications", "opening", 1], { results: [], count: 0, page: 1, pages: 1 });
  vi.mocked(recruitingApi.update).mockRejectedValue(new APIError(409, { error: { message: "Opening changed. Reload before editing." } }));
  await renderTeam("/find-team?listing=opening"); await click("Edit opening");
  const form = container.querySelector('[name="title"]')!.closest("form")!; await submit(form);
  expect(recruitingApi.update).toHaveBeenCalledWith("opening", expect.objectContaining({ expected_updated_at: listing.updated_at }));
  const submitted = vi.mocked(recruitingApi.update).mock.calls[0]![1] as object;
  expect(submitted).not.toHaveProperty("project"); expect(submitted).not.toHaveProperty("publish_consent");
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("Opening changed");
  expect(container.querySelector('[name="title"]')).not.toBeNull();
});
it("retains upload details on a scanner failure and never shows false success", async () => {
  vi.mocked(privateFilesApi.upload).mockRejectedValue(new APIError(400, { error: { message: "Malware scanner unavailable." } }));
  await renderFiles(); const title = container.querySelector<HTMLInputElement>('[name="title"]')!; title.value = "Keep my brief";
  await submit(title.closest("form")!);
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("scanner unavailable");
  expect(title.value).toBe("Keep my brief"); expect(container.textContent).not.toContain("Project files updated.");
});
it("shows archived files for download with no upload or editing actions", async () => {
  cache.setQueryData(["project", "team"], { id: "team", current_user_role: "owner", archived_at: "2026-10-02" });
  await renderFiles(); expect(container.querySelector('input[type="file"]')).toBeNull();
  expect(container.textContent).not.toContain("Edit details");
  expect(container.querySelector<HTMLAnchorElement>('[href="/download/brief"]')?.textContent).toContain("brief.txt");
});
it("uses the current document revision when adding a new version", async () => {
  cache.setQueryData(["private-file", "team", "doc"], doc);
  vi.mocked(privateFilesApi.version).mockResolvedValue(doc);
  vi.mocked(privateFilesApi.detail).mockResolvedValue(doc);
  await renderFiles(); await click("Versions"); const form = container.querySelector('[name="file"]')!.closest("form")!;
  const forms = Array.from(container.querySelectorAll("form")); const versionForm = forms.find(item => item.textContent?.includes("Upload new version"))!;
  expect(form).not.toBe(versionForm); await submit(versionForm);
  const body = vi.mocked(privateFilesApi.version).mock.calls[0]![2];
  expect(body.get("expected_revision")).toBe("4");
  expect(container.textContent).toContain("Not malware scanned");
});
