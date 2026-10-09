import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import TaskProductivity from "./TaskProductivity";
import { productivityApi as api, type ProductivityOverview, type TimeEntry } from "../api/productivity";

vi.mock("../api/productivity", () => ({ productivityApi: { overview: vi.fn(), startTimer: vi.fn(), stopTimer: vi.fn(), discardTimer: vi.fn(), addManual: vi.fn(), correct: vi.fn(), discard: vi.fn(), createSchedule: vi.fn(), stopSchedule: vi.fn() } }));
const entry: TimeEntry = { id: "entry", started_at: "2026-10-01T00:00:00Z", ended_at: "2026-10-01T01:00:00Z", seconds: 3600, source: "manual", note: "Private notes", cancelled_at: null, corrected_at: null, capped: false, updated_at: "2026-10-01T01:00:00Z" };
const overview: ProductivityOverview = { schedules: [], entries: [], page: 1, pages: 1, total: 0, active_timer: null, actual_seconds: 7200, my_seconds: 3600, timezone_name: "Australia/Sydney", read_only: false, can_stop_schedules: true };
let root: Root, container: HTMLDivElement, cache: QueryClient;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); vi.clearAllMocks();
  document.documentElement.dataset.timeZone = "Australia/Sydney";
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  cache = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
  cache.setQueryData(["productivity", "project", "task", 1], overview);
  vi.mocked(api.overview).mockResolvedValue(overview); vi.mocked(api.startTimer).mockResolvedValue(entry); vi.mocked(api.stopTimer).mockResolvedValue(entry); vi.mocked(api.addManual).mockResolvedValue(entry); vi.mocked(api.correct).mockResolvedValue(entry);
});
afterEach(async () => { await act(async () => root.unmount()); cache.clear(); container.remove(); delete document.documentElement.dataset.timeZone; });
async function render(readOnly = false) { await act(async () => root.render(<QueryClientProvider client={cache}><MemoryRouter><TaskProductivity projectId="project" taskId="task" readOnly={readOnly} /></MemoryRouter></QueryClientProvider>)); }
async function settle() { await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); }); }
const button = (label: string) => [...container.querySelectorAll<HTMLButtonElement>("button")].find(element => element.textContent === label)!;
async function submit(form: HTMLFormElement) { await act(async () => form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))); await settle(); }

it("starts a real timer through the task-scoped API and exposes factual totals", async () => {
  await render(); expect(container.textContent).toContain("Team recorded time: 2.00 h");
  await act(async () => button("Start timer").click()); await settle();
  expect(api.startTimer).toHaveBeenCalledWith("project", "task");
  expect(container.textContent).toContain("Saved.");
});

it("stops an active timer on the current task with the private note", async () => {
  const data = { ...overview, active_timer: { id: "timer", started_at: new Date(Date.now() - 60000).toISOString(), accessible: true, task_id: "task", project_id: "project", title: "Read chapter", read_only: false } };
  cache.setQueryData(["productivity", "project", "task", 1], data); vi.mocked(api.overview).mockResolvedValue(data);
  await render(); expect(container.textContent).toContain("Timer running on this task");
  await act(async () => button("Stop and record time").click()); await settle();
  expect(api.stopTimer).toHaveBeenCalledWith("project", "task", "");
});

it("does not reveal a removed project timer and offers discard recovery", async () => {
  cache.setQueryData(["productivity", "project", "task", 1], { ...overview, active_timer: { id: "timer", started_at: "2026-10-01T00:00:00Z", accessible: false, task_id: null, project_id: null, title: null, read_only: true } });
  await render(); expect(container.textContent).toContain("project you can no longer access");
  expect(button("Start timer")).toBeUndefined(); expect(button("Stop and record time")).toBeUndefined();
  expect(button("Discard running timer")).toBeDefined();
});

it("converts manual profile-zone times to explicit UTC offsets", async () => {
  await render(); const form = container.querySelector<HTMLFormElement>("form")!;
  form.querySelector<HTMLInputElement>('input[name="started_at"]')!.value = "2026-10-01T10:00";
  form.querySelector<HTMLInputElement>('input[name="minutes"]')!.value = "90";
  form.querySelector<HTMLTextAreaElement>('textarea[name="note"]')!.value = "Focused work";
  await submit(form);
  expect(api.addManual).toHaveBeenCalledWith("project", "task", { started_at: "2026-10-01T00:00:00.000Z", minutes: 90, note: "Focused work" });
});

it("corrects the selected record with its original conflict version", async () => {
  cache.setQueryData(["productivity", "project", "task", 1], { ...overview, entries: [entry] });
  await render(); await act(async () => button("Correct").click());
  const form = container.querySelector<HTMLFormElement>("form")!;
  form.querySelector<HTMLInputElement>('input[name="minutes"]')!.value = "30";
  await submit(form);
  expect(api.correct).toHaveBeenCalledWith("project", "task", entry, { started_at: "2026-10-01T00:00:00.000Z", minutes: 30, note: "Private notes" });
});

it("creates monthly task schedules with explicitly selected local timezone and lead days", async () => {
  await render(); const form = [...container.querySelectorAll<HTMLFormElement>("form")].find(item => item.querySelector('[name="frequency"]'))!;
  form.querySelector<HTMLSelectElement>('[name="frequency"]')!.value = "monthly";
  form.querySelector<HTMLInputElement>('[name="start_local"]')!.value = "2027-01-31T17:00";
  form.querySelector<HTMLInputElement>('[name="until_date"]')!.value = "2027-12-31";
  await submit(form);
  expect(api.createSchedule).toHaveBeenCalledWith("project", "task", { frequency: "monthly", interval: 1, timezone_name: "Australia/Sydney", start_local: "2027-01-31T17:00", until_date: "2027-12-31", occurrence_limit: 12, lead_days: 7 });
  expect(container.textContent).toContain("last available day"); expect(container.textContent).toContain("dependencies");
});

it("keeps a failed correction editable and explains its stale-version failure", async () => {
  cache.setQueryData(["productivity", "project", "task", 1], { ...overview, entries: [entry] });
  vi.mocked(api.correct).mockRejectedValue(new Error("This time record changed. Reload before correcting it."));
  await render(); await act(async () => button("Correct").click()); await submit(container.querySelector<HTMLFormElement>("form")!);
  expect(container.textContent).toContain("Reload before correcting"); expect(button("Save correction")).toBeDefined();
});

it("removes mutation controls from archived projects and tasks", async () => {
  cache.setQueryData(["productivity", "project", "task", 1], { ...overview, entries: [entry] });
  await render(true); expect(container.textContent).toContain("records are read-only");
  expect(container.querySelector("form")).toBeNull(); expect(button("Start timer")).toBeUndefined(); expect(button("Correct")).toBeUndefined();
});

it("only exposes schedule-stop controls when backend authorization permits", async () => {
  cache.setQueryData(["productivity", "project", "task", 1], { ...overview, schedules: [{ id: "schedule", author_id: "other", frequency: "weekly", interval: 1, timezone_name: "Australia/Sydney", start_local: "2026-11-01T17:00:00", until_date: "2027-11-01", occurrence_limit: 12, lead_days: 7, generated_count: 1, next_run_at: "2026-11-01T00:00:00Z", next_due_at: "2026-11-08T06:00:00Z", stopped_at: null, stop_reason: "", updated_at: "2026-10-01T00:00:00Z", can_stop: false }] });
  await render(); expect(button("Stop schedule")).toBeUndefined(); expect(button("Create schedule")).toBeUndefined();
});
