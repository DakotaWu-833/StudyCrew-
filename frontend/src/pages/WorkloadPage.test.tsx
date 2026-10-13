import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import WorkloadPage from "./WorkloadPage";
import { productivityApi as api, type Workload } from "../api/productivity";
vi.mock("../api/productivity", () => ({ productivityApi: { workload: vi.fn() } }));
const due = { overdue: 1, next_7_days: 2, later: 0, no_deadline: 1 };
const data: Workload = { project: { id: "team", name: "Study team" }, as_of: "2026-10-02T00:00:00Z", actual_seconds: 7200, method: "Estimates are divided equally. Running timers are excluded.", members: [
  { user_id: "a", name: "First member", current_member: true, open_tasks: 4, assigned_estimate_hours: "3.00", actual_seconds: 1800, due },
  { user_id: "b", name: "Former member", current_member: false, open_tasks: 0, assigned_estimate_hours: "0.00", actual_seconds: 5400, due: { overdue: 0, next_7_days: 0, later: 0, no_deadline: 0 } },
], unassigned: { open_tasks: 1, estimate_hours: "2.00", due } };
let root: Root, container: HTMLDivElement, cache: QueryClient;
beforeEach(() => { Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); vi.clearAllMocks(); container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container); cache = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } }); cache.setQueryData(["workload", "team"], data); vi.mocked(api.workload).mockResolvedValue(data); });
afterEach(async () => { await act(async () => root.unmount()); cache.clear(); container.remove(); });
async function render() { await act(async () => root.render(<QueryClientProvider client={cache}><MemoryRouter initialEntries={["/projects/team/workload"]}><Routes><Route path="/projects/:projectId/workload" element={<WorkloadPage />} /></Routes></MemoryRouter></QueryClientProvider>)); }
it("preserves member order while displaying separate estimates and actual recorded time", async () => { await render(); const headings = [...container.querySelectorAll("h2")].map(item => item.textContent); expect(headings.indexOf("First member")).toBeLessThan(headings.indexOf("Former member · former member")); expect(container.textContent).toContain("0.50 h"); expect(container.textContent).toContain("1.50 h"); expect(container.textContent).toContain("does not establish contribution quality"); });
it("shows deadline counts with accessible text and unassigned estimates", async () => { await render(); expect(container.textContent).toContain("1 overdue · 2 next 7 days"); expect(container.textContent).toContain("1 open tasks · 2.00 estimated hours"); expect(container.querySelectorAll('.productivity-due-bar[aria-hidden="true"]').length).toBe(3); });
it("escapes member names as text", async () => { cache.setQueryData(["workload", "team"], { ...data, members: [{ ...data.members[0]!, name: "<img src=x onerror=alert(1)>" }] }); await render(); expect(container.querySelector("img")).toBeNull(); expect(container.textContent).toContain("<img src=x onerror=alert(1)>"); });
