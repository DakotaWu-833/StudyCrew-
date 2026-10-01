import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { projectApi, taskApi } from "../api/resources";
import type { Comment, Me, Membership, Project, Task } from "../api/types";
import ProjectOverviewPage from "./ProjectOverviewPage";
import TaskDetailPage from "./TaskDetailPage";

vi.mock("../api/resources", () => ({
  accountApi: { me: vi.fn() },
  projectApi: { get: vi.fn(), update: vi.fn(), archive: vi.fn() },
  membershipApi: { list: vi.fn(), updateRole: vi.fn(), remove: vi.fn(), transferOwnership: vi.fn() },
  invitationApi: { listForProject: vi.fn(), create: vi.fn(), cancel: vi.fn() },
  taskApi: { get: vi.fn(), update: vi.fn(), setAssignees: vi.fn(), transition: vi.fn(), archive: vi.fn(), sendReminder: vi.fn() },
  commentApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(), report: vi.fn() },
}));

const owner = { id: "owner", display_name: "Alex Morgan" };
const teammate = { id: "member", display_name: "Mia Chen" };
const project: Project = {
  id: "project", name: "Team project", description: "Working together.", due_at: null,
  created_by: owner, created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
  archived_at: null, current_user_role: "owner", member_count: 2,
};
const task: Task = {
  id: "task", project: project.id, title: "Write proposal", description: "Agree on the direction.", status: "blocked",
  priority: "medium", blocker_note: "Awaiting research.", due_at: null, completed_at: null,
  created_by: owner, created_at: project.created_at, updated_at: project.updated_at, archived_at: null,
  assignees: [owner], comment_count: 1,
};
const member: Membership = { id: "membership", project: project.id, user: owner, role: "owner", joined_at: project.created_at, removed_at: null };
const comment: Comment = { id: "comment", task: task.id, author: teammate, body: "We can review this tomorrow.", created_at: project.created_at, edited_at: null, deleted_at: null, is_deleted: false };
const me: Me = {
  user: owner, email: "alex@example.com", permissions: { site_moderator: false },
  profile: { email: "alex@example.com", display_name: owner.display_name, course_code: "", time_zone: "Australia/Sydney", biography: "", avatar_url: "", avatar_image_url: "", updated_at: project.updated_at },
};
const originalDialogMethods = {
  showModal: Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "showModal"),
  close: Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "close"),
};

describe("editable workspace panel guards", () => {
  let container: HTMLDivElement;
  let root: Root;
  let client: QueryClient;

  beforeEach(() => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    vi.clearAllMocks();
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: true }));
    Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function (this: HTMLDialogElement) { this.setAttribute("open", ""); } });
    Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function (this: HTMLDialogElement) { this.removeAttribute("open"); } });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
    client.setQueryData(["project", project.id], project);
    client.setQueryData(["task", task.id], task);
    client.setQueryData(["memberships", project.id], { count: 1, results: [member], next: null, previous: null });
    client.setQueryData(["comments", task.id], { count: 1, results: [comment], next: null, previous: null });
    client.setQueryData(["invitations", project.id], { count: 0, results: [], next: null, previous: null });
    client.setQueryData(["me"], me);
    vi.mocked(projectApi.get).mockResolvedValue(project);
    vi.mocked(taskApi.get).mockResolvedValue(task);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    client.clear();
    container.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    for (const method of ["showModal", "close"] as const) {
      const original = originalDialogMethods[method];
      if (original) Object.defineProperty(HTMLDialogElement.prototype, method, original);
      else Reflect.deleteProperty(HTMLDialogElement.prototype, method);
    }
  });

  async function renderPage(page: "project" | "task") {
    const path = page === "project" ? "/app/projects/project/" : "/app/projects/project/tasks/task/";
    await act(async () => root.render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><Routes>
      <Route path="/app/projects/:projectId/" element={<ProjectOverviewPage />} />
      <Route path="/app/projects/:projectId/tasks/:taskId/" element={<TaskDetailPage />} />
    </Routes></MemoryRouter></QueryClientProvider>));
  }

  function button(label: string) {
    return [...container.querySelectorAll<HTMLButtonElement>("button")].find((element) => element.textContent === label)!;
  }

  function setValue(input: HTMLInputElement | HTMLTextAreaElement, value: string) {
    const prototype = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value")?.set?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }

  it("guards project drafts and opens a fresh clean form after explicit discard", async () => {
    await renderPage("project");
    await act(async () => button("Edit").click());
    let dialog = container.querySelector<HTMLDialogElement>("dialog")!;
    expect([...dialog.querySelectorAll("button")].some((element) => element.textContent === "Cancel")).toBe(false);
    await act(async () => setValue(dialog.querySelector<HTMLInputElement>('[name="name"]')!, "Unfinished project"));
    await act(async () => dialog.dispatchEvent(new Event("cancel", { cancelable: true })));
    expect(dialog.textContent).toContain("Discard unsaved changes?");
    await act(async () => button("Discard changes").click());
    expect(container.querySelector("dialog")).toBeNull();
    await act(async () => button("Edit").click());
    dialog = container.querySelector<HTMLDialogElement>("dialog")!;
    expect(dialog.querySelector<HTMLInputElement>('[name="name"]')?.value).toBe(project.name);
    await act(async () => dialog.dispatchEvent(new Event("cancel", { cancelable: true })));
    expect(container.querySelector("dialog")).toBeNull();
  });

  it.each([
    { trigger: "Edit details", title: "Edit task details", selector: '[name="title"]' },
    { trigger: "Update blocker note", title: "Describe the blocker", selector: '[name="blocker_note"]' },
    { trigger: "Moderate", title: "Moderate comment", selector: '[name="body"]' },
    { trigger: "Report", title: "Report comment", selector: '[name="details"]' },
  ])("protects unsaved $title without a second dialog", async ({ trigger, title, selector }) => {
    await renderPage("task");
    await act(async () => button(trigger).click());
    const dialog = container.querySelector<HTMLDialogElement>("dialog")!;
    expect(dialog.querySelector("h2")?.textContent).toBe(title);
    expect([...dialog.querySelectorAll("button")].some((element) => element.textContent === "Cancel")).toBe(false);
    const input = dialog.querySelector<HTMLInputElement | HTMLTextAreaElement>(selector)!;
    await act(async () => setValue(input, "Unsaved draft details"));
    await act(async () => dialog.dispatchEvent(new Event("cancel", { cancelable: true })));
    expect(dialog.textContent).toContain("Discard unsaved changes?");
    expect(container.querySelectorAll("dialog")).toHaveLength(1);
    await act(async () => button("Keep editing").click());
    expect(input.value).toBe("Unsaved draft details");
    expect(dialog.textContent).not.toContain("Discard unsaved changes?");
    await act(async () => dialog.dispatchEvent(new Event("cancel", { cancelable: true })));
    await act(async () => button("Discard changes").click());
    expect(container.querySelector("dialog")).toBeNull();
  });

  it.each(["project", "task"] as const)("keeps a %s save open while pending and closes directly after success", async (page) => {
    let complete: (value: Project | Task) => void = () => {};
    const pending = new Promise<Project | Task>((resolve) => { complete = resolve; });
    if (page === "project") vi.mocked(projectApi.update).mockReturnValue(pending as Promise<Project>);
    else vi.mocked(taskApi.update).mockReturnValue(pending as Promise<Task>);
    await renderPage(page);
    await act(async () => button(page === "project" ? "Edit" : "Edit details").click());
    const dialog = container.querySelector<HTMLDialogElement>("dialog")!;
    await act(async () => dialog.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
    expect(dialog.getAttribute("aria-busy")).toBe("true");
    await act(async () => dialog.dispatchEvent(new Event("cancel", { cancelable: true })));
    expect(dialog.open).toBe(true);
    expect(dialog.textContent).not.toContain("Discard unsaved changes?");
    await act(async () => complete(page === "project" ? project : task));
    await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
    expect(container.querySelector("dialog")).toBeNull();
    expect(container.textContent).toContain(page === "project" ? "Project details saved." : "Task details saved.");
  });
});
