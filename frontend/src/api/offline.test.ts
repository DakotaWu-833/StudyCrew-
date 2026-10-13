import { IDBFactory } from "fake-indexeddb";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { APIError } from "./client";
import { accountApi } from "./resources";
import type { Me, Task } from "./types";
import { enableOffline, keepTaskOffline, queueTaskEdit, readOffline } from "../app/offlineTasks";
import { offlineApi, syncOfflineTasks } from "./offline";

vi.mock("./resources", () => ({ accountApi: { me: vi.fn() } }));
const user = { id: "owner", display_name: "Alex" };
const me: Me = { user, email: "alex@example.com", profile: { email: "alex@example.com", display_name: "Alex", course_code: "", time_zone: "UTC", biography: "", avatar_url: "", avatar_image_url: "", updated_at: "2026-10-02T00:00:00Z" }, permissions: { site_moderator: false } };
const task: Task = { id: "task-1", project: "project-a", title: "Review proposal", description: "Introduction", status: "todo", priority: "medium", blocker_note: "", due_at: null, completed_at: null, created_by: user, created_at: "2026-10-02T00:00:00Z", updated_at: "2026-10-02T00:00:00Z", archived_at: null, assignees: [user], comment_count: 0 };
beforeEach(() => {
  vi.stubGlobal("indexedDB", new IDBFactory());
  vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
  vi.mocked(accountApi.me).mockReset().mockResolvedValue(me);
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function queued() { await enableOffline(me); await keepTaskOffline(me, task, "Studio team"); await queueTaskEdit(user.id, task.id, { title: "Local title" }); return (await readOffline())!.tasks[task.id]!; }

describe("offline synchronization", () => {
  it("transports the server revision and exact mutation nonce in an authenticated JSON request", async () => {
    document.cookie = "csrftoken=offline-csrf";
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ task, duplicate: false }), { status: 200 }));
    await offlineApi.sync(task.id, "saved-mutation", task.updated_at, { title: "Local title", due_at: null }, user.id);
    expect(fetch).toHaveBeenCalledWith(`/api/v1/offline/tasks/${task.id}/sync/`, expect.objectContaining({ method: "POST", credentials: "same-origin", body: JSON.stringify({ expected_user_id: user.id, mutation_id: "saved-mutation", expected_updated_at: task.updated_at, changes: { title: "Local title", due_at: null } }) }));
    expect(new Headers(fetch.mock.calls[0]![1]?.headers).get("X-CSRFToken")).toBe("offline-csrf");
  });

  it("retains the same nonce after an uncertain transport failure and retries that exact edit", async () => {
    const pending = await queued();
    const saved = { ...task, title: "Local title", updated_at: "2026-10-02T01:00:00Z" };
    const sync = vi.spyOn(offlineApi, "sync").mockRejectedValueOnce(new TypeError("Network disconnected")).mockResolvedValueOnce({ task: saved, duplicate: true });
    await syncOfflineTasks();
    expect((await readOffline())?.tasks[task.id]?.mutationId).toBe(pending.mutationId);
    await syncOfflineTasks();
    expect(sync.mock.calls).toEqual([[task.id, pending.mutationId, task.updated_at, { title: "Local title" }, user.id], [task.id, pending.mutationId, task.updated_at, { title: "Local title" }, user.id]]);
    expect((await readOffline())?.tasks[task.id]).toMatchObject({ base: saved, changes: {} });
    expect((await readOffline())?.tasks[task.id]?.mutationId).toBeUndefined();
  });

  it.each([401, 403, 404])("removes cached private content on a %i authorization or disappearance response", async status => {
    await queued(); vi.spyOn(offlineApi, "sync").mockRejectedValue(new APIError(status, { error: { message: "No access" } }));
    await syncOfflineTasks(); expect((await readOffline())?.tasks).toEqual({});
  });

  it("records a conflict without automatic retries or discarding pending changes", async () => {
    const pending = await queued(); const current = { ...task, title: "Server title", updated_at: "2026-10-02T01:00:00Z" };
    const sync = vi.spyOn(offlineApi, "sync").mockRejectedValue(new APIError(409, { current, error: { message: "Task changed" } }));
    await syncOfflineTasks(); await syncOfflineTasks();
    expect(sync).toHaveBeenCalledTimes(1);
    expect((await readOffline())?.tasks[task.id]).toMatchObject({ changes: { title: "Local title" }, mutationId: pending.mutationId, conflict: current });
  });

  it("retains validation failures for correction and releases the sync lock after identity lookup fails", async () => {
    await queued();
    vi.mocked(accountApi.me).mockRejectedValueOnce(new Error("Temporary login lookup failure"));
    await expect(syncOfflineTasks()).rejects.toThrow("Temporary login");
    vi.spyOn(offlineApi, "sync").mockRejectedValue(new APIError(400, { error: { message: "Required review is missing" } }));
    await syncOfflineTasks();
    expect((await readOffline())?.tasks[task.id]).toMatchObject({ error: "Required review is missing", changes: { title: "Local title" } });
  });

  it("checks server account identity before syncing and drops copies belonging to the previous account", async () => {
    await queued(); vi.mocked(accountApi.me).mockResolvedValue({ ...me, user: { id: "other", display_name: "Sam" } });
    const sync = vi.spyOn(offlineApi, "sync"); await syncOfflineTasks();
    expect(sync).not.toHaveBeenCalled(); expect(await readOffline()).toBeUndefined();
  });

  it("makes no network requests while offline", async () => {
    await queued(); vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    const sync = vi.spyOn(offlineApi, "sync"); await syncOfflineTasks();
    expect(accountApi.me).not.toHaveBeenCalled(); expect(sync).not.toHaveBeenCalled();
    expect((await readOffline())?.tasks[task.id]?.mutationId).toBeTruthy();
  });

  it("does not send duplicate requests when reconnect and a manual sync overlap", async () => {
    await queued();
    let finish!: (value: { task: Task; duplicate: boolean }) => void;
    let requestStarted!: () => void;
    const started = new Promise<void>(resolve => { requestStarted = resolve; });
    const response = new Promise<{ task: Task; duplicate: boolean }>(resolve => { finish = resolve; });
    const sync = vi.spyOn(offlineApi, "sync").mockImplementation(() => { requestStarted(); return response; });
    const first = syncOfflineTasks(); await started;
    await syncOfflineTasks(); expect(sync).toHaveBeenCalledTimes(1); expect(accountApi.me).toHaveBeenCalledTimes(1);
    finish({ task: { ...task, title: "Local title" }, duplicate: false }); await first;
    expect((await readOffline())?.tasks[task.id]?.mutationId).toBeUndefined();
  });

  it("preserves a newer edit saved while an older request is waiting for its response", async () => {
    const pending = await queued();
    let finish!: (value: { task: Task; duplicate: boolean }) => void;
    let requestStarted!: () => void;
    const started = new Promise<void>(resolve => { requestStarted = resolve; });
    const response = new Promise<{ task: Task; duplicate: boolean }>(resolve => { finish = resolve; });
    vi.spyOn(offlineApi, "sync").mockImplementation(() => { requestStarted(); return response; });
    const synchronizing = syncOfflineTasks(); await started;
    await queueTaskEdit(user.id, task.id, { title: "Newer offline title" });
    const newer = (await readOffline())!.tasks[task.id]!.mutationId;
    finish({ task: { ...task, title: "Local title", updated_at: "2026-10-02T01:00:00Z" }, duplicate: false });
    await synchronizing;
    expect(newer).not.toBe(pending.mutationId);
    expect((await readOffline())?.tasks[task.id]).toMatchObject({ mutationId: newer, changes: { title: "Newer offline title" }, base: { title: task.title } });
  });
});
