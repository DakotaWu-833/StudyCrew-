import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import LearningExchangePage from "./LearningExchangePage";
import { learningExchangeApi as api, type LearningOverview, type LearningPreview } from "../api/learningExchange";

vi.mock("../api/learningExchange", () => ({ learningExchangeApi: { overview: vi.fn(), preview: vi.fn(), confirm: vi.fn(), sampleUrl: "/api/v1/learning-exchange/sample/", exportUrl: (project: string, batch?: string) => `/api/v1/learning-exchange/projects/${project}/${batch ? `batches/${batch}/` : ""}export/` } }));
const overview: LearningOverview = { project: { id: "team", name: "Private study team", archived_at: null, can_import: true }, timezone_name: "Australia/Sydney", batches: [], page: 1, pages: 1, total: 0 };
const preview: LearningPreview = { valid: true, preview_id: "preview-1", expires_at: "2026-10-03T01:00:00Z", timezone_name: "Australia/Sydney", source: "generic", source_namespace: "COMP1010", ignored_columns: [], create_count: 1, skip_count: 0, rows: [{ row: 2, source_id: "assignment-1", title: "Final report", description: "Write report", priority: "high", official_due_at: "2026-11-15T06:00:00+00:00", errors: [], action: "create", existing_task: null }] };
let root: Root, container: HTMLDivElement, cache: QueryClient;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); vi.clearAllMocks();
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  cache = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
  cache.setQueryData(["learning-exchange", "team", 1], overview);
  vi.mocked(api.overview).mockResolvedValue(overview); vi.mocked(api.preview).mockResolvedValue(preview);
  vi.mocked(api.confirm).mockResolvedValue({ batch: { id: "batch-1", source: "generic", source_namespace: "COMP1010", timezone_name: "Australia/Sydney", created_at: "2026-10-02T01:00:00Z", imported_count: 1, skipped_count: 0 }, replayed: false });
  const NativeFormData = globalThis.FormData;
  vi.stubGlobal("FormData", class extends NativeFormData {
    constructor(form?: HTMLFormElement) { super(form); if (form?.querySelector('input[name="file"]')) this.set("file", new File(["title\nFinal report\n"], "assignments.csv", { type: "text/csv" })); }
  });
});
afterEach(async () => { await act(async () => root.unmount()); cache.clear(); container.remove(); vi.unstubAllGlobals(); });
async function render() { await act(async () => root.render(<QueryClientProvider client={cache}><MemoryRouter initialEntries={["/projects/team/learning"]}><Routes><Route path="/projects/:projectId/learning" element={<LearningExchangePage />} /></Routes></MemoryRouter></QueryClientProvider>)); }
async function settle() { await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); }); }
async function upload() { const form = container.querySelector("form")!; await act(async () => form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))); await settle(); }
const button = (label: string) => [...container.querySelectorAll<HTMLButtonElement>("button")].find(element => element.textContent === label)!;

it("previews the actual multipart form without creating tasks before explicit confirmation", async () => {
  await render(); await upload();
  expect(api.preview).toHaveBeenCalledOnce();
  const form = vi.mocked(api.preview).mock.calls[0]![1];
  expect(form.get("timezone_name")).toBe("Australia/Sydney"); expect(form.get("file")).toBeInstanceOf(File);
  expect(container.textContent).toContain("Final report"); expect(api.confirm).not.toHaveBeenCalled();
  expect(button("Confirm import").disabled).toBe(true);
  await act(async () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
  await act(async () => button("Confirm import").click()); await settle();
  expect(api.confirm).toHaveBeenCalledWith("team", "preview-1");
  expect(container.textContent).toContain("Imported 1 assignments");
  expect(container.textContent).not.toContain("2. Review every assignment");
});

it("shows complete invalid rows and offers no confirm control", async () => {
  vi.mocked(api.preview).mockResolvedValue({ ...preview, valid: false, preview_id: null, rows: [{ ...preview.rows[0]!, errors: ["This local time is missing or repeated during daylight saving."] }] });
  await render(); await upload();
  expect(container.textContent).toContain("no tasks have been created");
  expect(container.textContent).toContain("daylight saving");
  expect(button("Confirm import")).toBeUndefined();
  expect(api.confirm).not.toHaveBeenCalled();
});

it("clearly marks duplicates and ignored columns in preview", async () => {
  vi.mocked(api.preview).mockResolvedValue({ ...preview, create_count: 0, skip_count: 1, ignored_columns: ["Grade"], rows: [{ ...preview.rows[0]!, action: "skip", existing_task: "task-1" }] });
  await render(); await upload();
  expect(container.textContent).toContain("1 existing source IDs to skip");
  expect(container.textContent).toContain("Skip existing assignment; never overwrite");
  expect(container.textContent).toContain("Ignored columns: Grade");
});

it("discarding an edited upload form invalidates its prior confirmation", async () => {
  await render(); await upload();
  await act(async () => container.querySelector<HTMLSelectElement>('select[name="source"]')!.dispatchEvent(new Event("change", { bubbles: true })));
  expect(container.textContent).not.toContain("2. Review every assignment");
  expect(api.confirm).not.toHaveBeenCalled();
});

it("retains the preview when confirmation fails so its errors remain reviewable", async () => {
  vi.mocked(api.confirm).mockRejectedValue(new Error("This preview expired. Upload the file again."));
  await render(); await upload();
  await act(async () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
  await act(async () => button("Confirm import").click()); await settle();
  expect(container.textContent).toContain("preview expired");
  expect(container.textContent).toContain("Final report");
});

it("reports idempotent replay without pretending to create another task", async () => {
  vi.mocked(api.confirm).mockResolvedValue({ batch: { id: "batch-1", source: "generic", source_namespace: "COMP1010", timezone_name: "Australia/Sydney", created_at: "2026-10-02T01:00:00Z", imported_count: 1, skipped_count: 0 }, replayed: true });
  await render(); await upload(); await act(async () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
  await act(async () => button("Confirm import").click()); await settle();
  expect(container.textContent).toContain("No duplicate tasks were created");
});

it("keeps current-task and batch-snapshot export links scoped to the displayed project", async () => {
  cache.setQueryData(["learning-exchange", "team", 1], { ...overview, batches: [{ id: "batch-1", source: "generic", source_namespace: "COMP1010", timezone_name: "Australia/Sydney", created_at: "2026-10-02T01:00:00Z", imported_count: 1, skipped_count: 1 }] });
  await render();
  expect(container.querySelector('a[href="/api/v1/learning-exchange/projects/team/export/"]')).not.toBeNull();
  expect(container.querySelector('a[href="/api/v1/learning-exchange/projects/team/batches/batch-1/export/"]')).not.toBeNull();
});

it("member and archived project pages expose only read-only exchange controls", async () => {
  cache.setQueryData(["learning-exchange", "team", 1], { ...overview, project: { ...overview.project, archived_at: "2026-10-01T00:00:00Z", can_import: false } });
  await render(); expect(container.textContent).toContain("imports are read-only"); expect(container.querySelector("form")).toBeNull();
  expect(container.querySelector('a[download]')).not.toBeNull();
});

it("escapes hostile assignment markup while showing literal formulas", async () => {
  vi.mocked(api.preview).mockResolvedValue({ ...preview, rows: [{ ...preview.rows[0]!, title: "<img src=x onerror=alert(1)>", description: "=SUM(1)" }] });
  await render(); await upload();
  expect(container.querySelector("img")).toBeNull(); expect(container.textContent).toContain("<img src=x onerror=alert(1)>"); expect(container.textContent).toContain("=SUM(1)");
});
