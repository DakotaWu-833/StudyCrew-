import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { taskApi } from "../api/resources";
import type { Me, Membership, Page, Project, Task } from "../api/types";
import TasksPage from "./TasksPage";

vi.mock("../api/resources", () => ({
  accountApi: { me: vi.fn() }, membershipApi: { list: vi.fn() }, projectApi: { get: vi.fn() },
  taskApi: { list: vi.fn(), create: vi.fn(), transition: vi.fn() },
}));

const user = { id: "owner", display_name: "Alex Morgan" };
const task: Task = { id: "task-1", project: "project-a", title: "Review the proposal", description: "Agree on the next step", status: "todo", priority: "medium", blocker_note: "", due_at: null, completed_at: null, created_by: user, created_at: "2026-09-30T10:00:00Z", updated_at: "2026-09-30T10:00:00Z", archived_at: null, assignees: [user], comment_count: 0 };
const taskPage: Page<Task> = { count: 1, results: [task], next: null, previous: null };
const project: Project = { id: "project-a", name: "Studio team", description: "", due_at: null, created_by: user, created_at: task.created_at, updated_at: task.updated_at, archived_at: null, current_user_role: "owner", member_count: 1 };
const members: Page<Membership> = { count: 1, results: [{ id: "membership-1", project: "project-a", user, role: "owner", joined_at: task.created_at, removed_at: null }], next: null, previous: null };
const me: Me = { user, email: "alex@example.com", profile: { email: "alex@example.com", display_name: user.display_name, course_code: "", time_zone: "UTC", biography: "", avatar_url: "", avatar_image_url: "", updated_at: task.updated_at }, permissions: { site_moderator: false } };
const originalDialogMethods = Object.fromEntries(["showModal", "close"].map((method) => [method, Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, method)]));

describe("TasksPage filters and stable results", () => {
  let container: HTMLDivElement;
  let root: Root;
  let client: QueryClient;

  beforeEach(() => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    vi.clearAllMocks();
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function (this: HTMLDialogElement) { this.setAttribute("open", ""); } });
    Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function (this: HTMLDialogElement) { this.removeAttribute("open"); } });
    container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
    client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
    client.setQueryData(["tasks", "project-a", {}], taskPage);
    for (const projectId of ["project-a", "project-b"]) {
      client.setQueryData(["project", projectId], { ...project, id: projectId });
      client.setQueryData(["memberships", projectId], members);
    }
    client.setQueryData(["me"], me);
    vi.mocked(taskApi.list).mockResolvedValue(taskPage);
  });

  afterEach(async () => {
    await act(async () => root.unmount()); client.clear(); container.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals();
    for (const method of ["showModal", "close"]) {
      if (originalDialogMethods[method]) Object.defineProperty(HTMLDialogElement.prototype, method, originalDialogMethods[method]);
      else Reflect.deleteProperty(HTMLDialogElement.prototype, method);
    }
  });

  const settle = async (delay = 20) => { await act(async () => { await new Promise((resolve) => setTimeout(resolve, delay)); }); };
  const clickButton = async (label: string) => { await act(async () => [...container.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === label)!.click()); };
  const render = async () => { await act(async () => root.render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/projects/project-a/tasks/"]}><Link id="other-project" to="/projects/project-b/tasks/">Other project</Link><Routes><Route path="/projects/:projectId/tasks/" element={<TasksPage />} /></Routes></MemoryRouter></QueryClientProvider>)); };

  it("restores applied selects when the filter dialog reopens and Clear closes it", async () => {
    await render(); await clickButton("Filters");
    const dialog = container.querySelector("dialog")!;
    const setSelect = (name: string, value: string) => { const select = dialog.querySelector<HTMLSelectElement>(`[name="${name}"]`)!; select.value = value; select.dispatchEvent(new Event("change", { bubbles: true })); };
    await act(async () => { setSelect("status", "done"); setSelect("priority", "urgent"); setSelect("scope", "archived"); setSelect("assignee", "owner"); setSelect("due", "overdue"); dialog.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
    await settle();
    expect(container.querySelector("dialog")).toBeNull();
    expect(container.textContent).toContain("5 filters");
    await clickButton("Filters");
    for (const [name, expected] of Object.entries({ status: "done", priority: "urgent", scope: "archived", assignee: "owner", due: "overdue" })) expect(container.querySelector<HTMLSelectElement>(`dialog [name="${name}"]`)!.value).toBe(expected);
    await clickButton("Clear"); await settle();
    expect(container.querySelector("dialog")).toBeNull();
    expect(container.textContent).not.toContain("5 filters");
    expect(taskApi.list).toHaveBeenCalledWith("project-a", expect.objectContaining({ status: "done", priority: "urgent", scope: "archived", assignee: "owner", due: "overdue" }));
  });

  it("keeps same-project cards during a filter request but never during navigation to another project", async () => {
    await render();
    vi.mocked(taskApi.list).mockImplementation(() => new Promise(() => {}));
    await clickButton("Filters");
    await act(async () => { const select = container.querySelector<HTMLSelectElement>('dialog [name="status"]')!; select.value = "done"; container.querySelector("dialog form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
    await settle();
    expect(container.textContent).toContain(task.title);
    expect(container.querySelector(".task-board")!.getAttribute("aria-busy")).toBe("true");
    expect(container.textContent).toContain("Updating task results…");
    await act(async () => container.querySelector<HTMLAnchorElement>("#other-project")!.click());
    await settle();
    expect(container.textContent).not.toContain(task.title);
    expect(container.textContent).toContain("Loading tasks…");
  });

  it("offers an accessible list mode without changing status or permission rules", async () => {
    await render(); await clickButton("List");
    expect(container.querySelector(".task-board--list")).not.toBeNull();
    expect([...container.querySelectorAll("button")].find((button) => button.textContent === "List")!.getAttribute("aria-pressed")).toBe("true");
    expect(container.querySelector('.task-card select[title="Change task status"]')).not.toBeNull();
    expect(container.querySelector(".task-card__status")!.textContent).toBe("todo");
    await clickButton("Board");
    expect(container.querySelector(".task-board--list")).toBeNull();
  });
});
