import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import ProjectFilesPage from "./ProjectFilesPage";
import { privateFilesApi as api, type ProjectDocument, type TrashPage } from "../api/privateFiles";

vi.mock("../api/privateFiles", () => ({ privateFilesApi: Object.fromEntries(["list", "detail", "upload", "update", "remove", "version", "preview", "compare", "trash", "restore"].map(name => [name, vi.fn()])) }));
vi.mock("../api/resources", () => ({ projectApi: { get: vi.fn() } }));
vi.mock("./PdfFilePreview", () => ({ default: () => <p>Canvas PDF preview</p> }));

const latest = { id: "v2", number: 2, filename: "notes.txt", content_type: "text/plain", size: 50, sha256: "a".repeat(64), scan_status: "local_unscanned", created_at: "2026-10-02T01:00:00Z", download_url: "/download/v2", preview_kind: "text" as const, preview_url: "/preview/v2" };
const earlier = { ...latest, id: "v1", number: 1, download_url: "/download/v1", preview_url: "/preview/v1" };
const documentRow: ProjectDocument = { id: "doc", project: "team", title: "Team notes", folder: "Briefs", tags: [], pinned: false, author: { id: "member", display_name: "Student" }, revision: 4, created_at: "2026-10-02", updated_at: "2026-10-02", can_edit: true, latest, versions: [latest, earlier] };
const trashPage: TrashPage = { results: [{ ...documentRow, latest: null, removed_at: "2026-10-02T01:00:00Z", purge_after: "2026-11-01T01:00:00Z", can_restore: true }], count: 1, page: 1, pages: 1, retention_days: 30 };
let root: Root, container: HTMLDivElement, cache: QueryClient;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); vi.clearAllMocks();
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  cache = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
  cache.setQueryData(["project", "team"], { id: "team", current_user_role: "owner", archived_at: null });
  const page = { results: [documentRow], count: 1, page: 1, pages: 1, usage: { bytes: 50, limit: 1024, file_limit: 1024, daily_bytes_limit: 1024, daily_upload_limit: 30 }, allowed_extensions: ["txt", "pdf", "png"], scan_required: false };
  cache.setQueryData(["private-files", "team", "", "", "", 1], page);
  cache.setQueryData(["private-file", "team", "doc"], documentRow);
  vi.mocked(api.list).mockResolvedValue(page);
  vi.mocked(api.detail).mockResolvedValue(documentRow);
  vi.mocked(api.trash).mockResolvedValue(trashPage);
  vi.mocked(api.restore).mockResolvedValue(documentRow);
  vi.mocked(api.compare).mockResolvedValue({ from_version: "v1", to_version: "v2", identical: false, truncated: false, lines: [{ kind: "removed", text: "-Old line" }, { kind: "added", text: "+<img src=x onerror=alert(1)>" }] });
  vi.mocked(api.preview).mockResolvedValue({ blob: { text: async () => "<script>alert('test')</script>\nNotes" } as Blob, truncated: false });
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:private-preview"), revokeObjectURL: vi.fn() }));
});
afterEach(async () => { await act(async () => root.unmount()); cache.clear(); container.remove(); vi.unstubAllGlobals(); });
async function render() { await act(async () => root.render(<QueryClientProvider client={cache}><MemoryRouter initialEntries={["/projects/team/files"]}><Routes><Route path="/projects/:projectId/files" element={<ProjectFilesPage />} /></Routes></MemoryRouter></QueryClientProvider>)); }
async function click(name: string) { const button = [...container.querySelectorAll<HTMLButtonElement>("button")].find(item => item.textContent === name)!; expect(button, `Missing ${name}`).toBeDefined(); await act(async () => { button.click(); await new Promise(resolve => setTimeout(resolve, 25)); }); }

it("previews current text privately and escapes markup without executing it", async () => {
  await render(); await click("Preview");
  expect(api.preview).toHaveBeenCalledWith("team", "doc", "v2");
  expect(container.querySelector("pre")?.textContent).toContain("<script>alert('test')</script>");
  expect(container.querySelector("script")).toBeNull();
  expect(container.querySelector("iframe")).toBeNull();
  expect(document.activeElement?.textContent).toContain("Preview · Version 2: notes.txt");
  await click("Close preview"); expect(container.querySelector("pre")).toBeNull();
});

it("shows bounded preview notice and lets an older version be previewed", async () => {
  vi.mocked(api.preview).mockResolvedValue({ blob: { text: async () => "Long text" } as Blob, truncated: true });
  await render(); await click("Versions"); await click("Preview version 1");
  expect(api.preview).toHaveBeenCalledWith("team", "doc", "v1");
  expect(container.textContent).toContain("Showing the first 512 KB");
});

it("creates temporary image blobs and revokes their URL when the preview closes", async () => {
  const image = { ...documentRow, latest: { ...latest, filename: "chart.png", content_type: "image/png", preview_kind: "image" as const } };
  cache.setQueryData(["private-files", "team", "", "", "", 1], { ...cache.getQueryData<object>(["private-files", "team", "", "", "", 1]), results: [image] });
  vi.mocked(api.preview).mockResolvedValue({ blob: new Blob(["image"], { type: "image/png" }), truncated: false });
  await render(); await click("Preview");
  expect(container.querySelector("img")?.getAttribute("src")).toBe("blob:private-preview");
  await click("Close preview"); expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:private-preview");
});

it("compares selected text version IDs and displays literal additions and removals", async () => {
  await render(); await click("Versions");
  const form = container.querySelector('select[name="from_version"]')!.closest("form")!;
  await act(async () => { form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); await new Promise(resolve => setTimeout(resolve, 25)); });
  expect(api.compare).toHaveBeenCalledWith("team", "doc", "v1", "v2");
  expect(container.querySelector(".diff-removed")?.textContent).toBe("-Old line");
  expect(container.querySelector(".diff-added")?.textContent).toBe("+<img src=x onerror=alert(1)>");
  expect(container.querySelector("img")).toBeNull();
});

it("keeps binary comparisons unavailable and reports diff errors without stale output", async () => {
  cache.setQueryData(["private-file", "team", "doc"], { ...documentRow, versions: [{ ...latest, preview_kind: "pdf" }, { ...earlier, preview_kind: "image" }] });
  await render(); await click("Versions"); expect(container.querySelector('select[name="from_version"]')).toBeNull();
  expect(api.compare).not.toHaveBeenCalled();
});

it("restores with current revision and provides no preview or download for recycle-bin rows", async () => {
  await render(); await click("Recycle bin");
  expect(api.trash).toHaveBeenCalledWith("team", "", 1);
  expect(container.querySelector('a[href="/download/v2"]')).toBeNull();
  expect(container.querySelector('input[type="file"]')).toBeNull();
  await click("Restore file");
  expect(api.restore).toHaveBeenCalledWith("team", "doc", 4);
  expect(container.textContent).toContain("Project files updated.");
});

it("retains recycle-bin evidence and shows no success when restoration fails", async () => {
  vi.mocked(api.restore).mockRejectedValue(new Error("The 30-day restoration period has ended."));
  await render(); await click("Recycle bin"); await click("Restore file");
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("restoration period has ended");
  expect(container.textContent).toContain("Team notes"); expect(container.textContent).not.toContain("Project files updated.");
});

it("shows archived project trash as read-only even if stale cached restore capability was true", async () => {
  cache.setQueryData(["project", "team"], { id: "team", current_user_role: "owner", archived_at: "2026-10-02" });
  await render(); await click("Recycle bin");
  expect(container.textContent).not.toContain("Restore file"); expect(container.textContent).toContain("read-only");
});

it("clears an open preview when switching to the recycle bin", async () => {
  await render(); await click("Preview"); await click("Recycle bin");
  expect(container.querySelector("pre")).toBeNull(); expect(container.textContent).not.toContain("Close preview");
});
