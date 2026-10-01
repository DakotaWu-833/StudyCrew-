import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { exportApi, projectApi } from "../api/resources";
import type { ActivityTimeline, Insights } from "../api/types";
import { today } from "../app/format";
import ContributionsPage from "./ContributionsPage";

vi.mock("../api/resources", () => ({ projectApi: { insights: vi.fn(), timeline: vi.fn() }, exportApi: { list: vi.fn(), create: vi.fn() } }));
const range = { range_start: today(-30), range_end: today(), event_type: "" };
const insights: Insights = { ...range, members: [{ user_id: "member-1", display_name: "Alex Morgan", role: "owner", total_events: 1, completed_tasks: 0, comments: 0, accepted_meetings: 0 }], events: [], events_truncated: false, charts: { task_status: [], task_priority: [], task_assignees: [], tasks_created: [], completion_cycle: [] } };
const timeline: ActivityTimeline = { events_total: 1, events_page: 1, events_pages: 1, events_page_size: 5, events: [{ id: "event-1", project: "project-a", actor: { id: "member-1", display_name: "Alex Morgan" }, event_type: "task_created", target_type: "task", target_id: "task-1", metadata: {}, occurred_at: "2026-09-30T10:00:00Z" }] };

describe("ContributionsPage stable activity controls", () => {
  let container: HTMLDivElement;
  let root: Root;
  let client: QueryClient;

  beforeEach(() => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); vi.clearAllMocks();
    container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
    client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
    client.setQueryData(["insights", "project-a", range], insights);
    client.setQueryData(["project-timeline", "project-a", range, "", "", 1], timeline);
    client.setQueryData(["exports"], { count: 0, results: [], next: null, previous: null });
    vi.mocked(projectApi.insights).mockResolvedValue(insights);
    vi.mocked(projectApi.timeline).mockResolvedValue(timeline);
    vi.mocked(exportApi.list).mockResolvedValue({ count: 0, results: [], next: null, previous: null });
  });
  afterEach(async () => { await act(async () => root.unmount()); client.clear(); container.remove(); vi.restoreAllMocks(); });
  const settle = async (delay = 20) => { await act(async () => { await new Promise((resolve) => setTimeout(resolve, delay)); }); };
  const render = async () => { await act(async () => root.render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/projects/project-a/contributions/"]}><Link id="other-project" to="/projects/project-b/contributions/">Other project</Link><Routes><Route path="/projects/:projectId/contributions/" element={<ContributionsPage />} /></Routes></MemoryRouter></QueryClientProvider>)); };
  const searchInput = () => container.querySelector<HTMLInputElement>('.timeline-controls input[type="search"]')!;
  const typeSearch = (input: HTMLInputElement, value: string) => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); };

  it("retains the same focused search and old events while search results load", async () => {
    await render();
    vi.mocked(projectApi.timeline).mockImplementation(() => new Promise(() => {}));
    const input = searchInput();
    await act(async () => { input.focus(); typeSearch(input, "Alex"); });
    await settle(300);
    expect(searchInput()).toBe(input);
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe("Alex");
    expect(container.querySelector(".timeline")!.textContent).toContain("task created");
    expect(container.querySelector(".timeline-results")!.getAttribute("aria-busy")).toBe("true");
    expect(projectApi.timeline).toHaveBeenLastCalledWith("project-a", expect.objectContaining({ search: "Alex", page: "1" }));
  });

  it("keeps search controls mounted after a failed or empty search", async () => {
    await render();
    const input = searchInput(); input.focus();
    vi.mocked(projectApi.timeline).mockRejectedValueOnce(new Error("Timeline unavailable."));
    await act(async () => typeSearch(input, "missing")); await settle(300); await settle();
    expect(searchInput()).toBe(input);
    expect(document.activeElement).toBe(input);
    expect(container.querySelector(".timeline-results")!.textContent).toContain("Timeline unavailable.");
    vi.mocked(projectApi.timeline).mockResolvedValueOnce({ ...timeline, events: [], events_total: 0 });
    await act(async () => typeSearch(input, "no results")); await settle(300); await settle();
    expect(searchInput()).toBe(input);
    expect(container.querySelector(".timeline-results")!.textContent).toContain("No matching activity");
  });

  it("shows activity controls during initial loading and never retains another project's events", async () => {
    await render();
    vi.mocked(projectApi.timeline).mockImplementation(() => new Promise(() => {}));
    vi.mocked(projectApi.insights).mockImplementation(() => new Promise(() => {}));
    await act(async () => container.querySelector<HTMLAnchorElement>("#other-project")!.click()); await settle();
    expect(searchInput()).not.toBeNull();
    expect(container.querySelector(".timeline")).toBeNull();
    expect(container.querySelector(".timeline-results")!.textContent).toContain("Loading activity timeline…");
  });

  it("exposes restored meetings and sends the exact supported activity contract to both queries", async () => {
    await render();
    const select = container.querySelector<HTMLSelectElement>('[name="event_type"]')!;
    expect([...select.options].find((option) => option.value === "meeting_restored")?.text).toBe("Meeting Restored");
    await act(async () => { select.value = "meeting_restored"; select.form!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); }); await settle();
    expect(projectApi.insights).toHaveBeenLastCalledWith("project-a", expect.objectContaining({ event_type: "meeting_restored" }));
    expect(projectApi.timeline).toHaveBeenLastCalledWith("project-a", expect.objectContaining({ event_type: "meeting_restored", page: "1" }));
  });
});
