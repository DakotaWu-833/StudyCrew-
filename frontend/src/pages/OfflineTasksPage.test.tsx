import { IDBFactory } from "fake-indexeddb";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { accountApi } from "../api/resources";
import { syncOfflineTasks } from "../api/offline";
import type { Me, Task } from "../api/types";
import { enableOffline, keepTaskOffline, queueTaskEdit, readOffline, recordSyncResult } from "../app/offlineTasks";
import OfflineTasksPage from "./OfflineTasksPage";

vi.mock("../api/resources", () => ({ accountApi: { me: vi.fn() } }));
vi.mock("../api/offline", () => ({ syncOfflineTasks: vi.fn() }));
const user = { id: "owner", display_name: "Alex" };
const me: Me = { user, email: "alex@example.com", profile: { email: "alex@example.com", display_name: "Alex", course_code: "", time_zone: "UTC", biography: "", avatar_url: "", avatar_image_url: "", updated_at: "2026-10-02T00:00:00Z" }, permissions: { site_moderator: false } };
const task: Task = { id: "task-1", project: "project-a", title: "Review proposal", description: "Introduction", status: "todo", priority: "medium", blocker_note: "", due_at: null, completed_at: null, created_by: user, created_at: "2026-10-02T00:00:00Z", updated_at: "2026-10-02T00:00:00Z", archived_at: null, assignees: [user], comment_count: 0 };
const dialogMethods = Object.fromEntries(["showModal", "close"].map(name => [name, Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, name)]));
let container: HTMLDivElement, root: Root;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); vi.clearAllMocks();
  vi.stubGlobal("indexedDB", new IDBFactory()); vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function (this: HTMLDialogElement) { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function (this: HTMLDialogElement) { this.removeAttribute("open"); } });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  vi.mocked(accountApi.me).mockResolvedValue(me); vi.mocked(syncOfflineTasks).mockResolvedValue(undefined);
});
afterEach(async () => {
  await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals();
  for (const name of ["showModal", "close"]) { if (dialogMethods[name]) Object.defineProperty(HTMLDialogElement.prototype, name, dialogMethods[name]); else Reflect.deleteProperty(HTMLDialogElement.prototype, name); }
});
async function saved() { await enableOffline(me); await keepTaskOffline(me, task, "Studio team"); }
async function settle() { await new Promise(resolve => setTimeout(resolve, 25)); }
async function render() { await act(async () => root.render(<MemoryRouter><OfflineTasksPage /></MemoryRouter>)); await act(settle); }
async function click(label: string) { const button = [...container.querySelectorAll<HTMLButtonElement>("button")].find(item => item.textContent === label)!; expect(button, `Missing ${label}`).toBeDefined(); await act(async () => { button.click(); await settle(); }); }
async function submit() { const form = container.querySelector("dialog form")!; await act(async () => { form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); await settle(); }); }

describe("offline task edit and conflict choices", () => {
  it("opens saved tasks without fetching account data and stores edits locally while disconnected", async () => {
    await saved(); await render();
    expect(accountApi.me).not.toHaveBeenCalled(); expect(container.textContent).toContain("Offline · edits stay on this device");
    expect(container.textContent).toContain("Saved for Alex");
    expect([...container.querySelectorAll<HTMLButtonElement>("button")].find(item => item.textContent === "Sync now")?.disabled).toBe(true);
    await click("Edit saved task");
    container.querySelector<HTMLInputElement>('input[name="title"]')!.value = "Offline revised proposal";
    await submit();
    expect(container.querySelector("dialog")).toBeNull(); expect(container.textContent).toContain("Pending sync");
    expect((await readOffline())?.tasks[task.id]?.changes).toEqual({ title: "Offline revised proposal" });
    expect(syncOfflineTasks).not.toHaveBeenCalled();
  });

  it("rejects a blocked status without a useful blocker and retains the edit form", async () => {
    await saved(); await render(); await click("Edit saved task");
    container.querySelector<HTMLSelectElement>('select[name="status"]')!.value = "blocked";
    await submit();
    expect(container.textContent).toContain("Describe the blocker using at least 3 characters.");
    expect(container.querySelector("dialog")).not.toBeNull();
    expect((await readOffline())?.tasks[task.id]?.mutationId).toBeUndefined();
  });

  it("shows explicit server/local conflict values and rebases only the field the user selects", async () => {
    await saved(); await queueTaskEdit(user.id, task.id, { title: "Local title", description: "Local description" });
    const pending = (await readOffline())!.tasks[task.id]!;
    await recordSyncResult(user.id, task.id, pending.mutationId!, { conflict: { ...task, title: "Server title", description: "Server description", updated_at: "2026-10-02T01:00:00Z" } });
    await render();
    expect(container.textContent).toContain("Conflict needs review"); expect(container.textContent).toContain("Server description");
    const checkboxes = [...container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')];
    expect(checkboxes.every(input => !input.checked)).toBe(true);
    await act(async () => container.querySelector<HTMLInputElement>('[aria-label="Keep local title"]')!.click());
    await click("Apply these choices");
    const row = (await readOffline())!.tasks[task.id]!;
    expect(row.changes).toEqual({ title: "Local title" }); expect(row.base.description).toBe("Server description");
    expect(container.textContent).not.toContain("Conflict needs review"); expect(container.textContent).toContain("Server description");
  });

  it("accepts server values when the user chooses no fields and returns the task to a saved copy", async () => {
    await saved(); await queueTaskEdit(user.id, task.id, { title: "Local title" });
    const pending = (await readOffline())!.tasks[task.id]!;
    await recordSyncResult(user.id, task.id, pending.mutationId!, { conflict: { ...task, title: "Server title" } });
    await render(); await click("Apply these choices");
    expect(container.textContent).toContain("Server title"); expect(container.textContent).toContain("Saved copy");
    expect((await readOffline())?.tasks[task.id]?.mutationId).toBeUndefined();
  });

  it("removes saved private content from the page and device storage", async () => {
    await saved(); await render(); await click("Remove device copy");
    expect(container.textContent).toContain("No saved tasks"); expect(container.textContent).not.toContain(task.description);
    expect((await readOffline())?.tasks).toEqual({});
    await click("Clear all device copies");
    expect(await readOffline()).toBeUndefined(); expect(container.textContent).toContain("Reconnect and sign in");
  });
});
