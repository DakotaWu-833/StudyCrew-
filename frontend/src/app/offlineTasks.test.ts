import { IDBFactory } from "fake-indexeddb";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Me, Task } from "../api/types";
import { changedFields, clearOffline, enableOffline, keepTaskOffline, offlineLifetime, queueTaskEdit, readOffline, recordSyncResult, removeOfflineTask, resolveOfflineConflict, verifyOfflineOwner } from "./offlineTasks";

const user = { id: "owner", display_name: "Alex" };
const me: Me = { user, email: "alex@example.com", profile: { email: "alex@example.com", display_name: "Alex", course_code: "", time_zone: "UTC", biography: "", avatar_url: "", avatar_image_url: "", updated_at: "2026-10-02T00:00:00Z" }, permissions: { site_moderator: false } };
const task: Task = { id: "task-1", project: "project-a", title: "Review the proposal", description: "Draft introduction", status: "todo", priority: "medium", blocker_note: "", due_at: "2026-10-03T00:00:00Z", completed_at: null, created_by: user, created_at: "2026-10-02T00:00:00Z", updated_at: "2026-10-02T00:00:00Z", archived_at: null, assignees: [user], comment_count: 0 };
let now: number;

beforeEach(() => {
  vi.stubGlobal("indexedDB", new IDBFactory());
  now = Date.parse("2026-10-02T00:00:00Z");
  vi.spyOn(Date, "now").mockImplementation(() => now);
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function save() { await enableOffline(me); await keepTaskOffline(me, task, "Studio team"); }
async function row() { return (await readOffline())?.tasks[task.id]; }

describe("private offline task copies", () => {
  it("requires explicit enablement and replaces the prior account's copies when another account enables storage", async () => {
    await expect(keepTaskOffline(me, task, "Studio team")).rejects.toThrow("Enable offline");
    await save();
    const other = { ...me, user: { id: "other", display_name: "Sam" } };
    await expect(queueTaskEdit(other.user.id, task.id, { title: "Wrong account" })).rejects.toThrow("expired");
    await removeOfflineTask(other.user.id, task.id);
    expect(await row()).toBeDefined();
    await enableOffline(other);
    expect(await readOffline()).toMatchObject({ ownerId: "other", ownerName: "Sam", tasks: {} });
  });

  it("clears the saved account when server identity verification reports a different account", async () => {
    await save();
    await verifyOfflineOwner({ ...me, user: { id: "other", display_name: "Sam" } });
    expect(await readOffline()).toBeUndefined();
  });

  it("expires both task content and pending edits at the 24-hour boundary", async () => {
    await save(); await queueTaskEdit(user.id, task.id, { title: "Offline draft" });
    now += offlineLifetime - 1;
    expect((await row())?.changes).toEqual({ title: "Offline draft" });
    now += 1;
    expect(await readOffline()).toBeUndefined();
    await expect(queueTaskEdit(user.id, task.id, { title: "Too late" })).rejects.toThrow("expired");
  });

  it("does not prolong old private task copies when the owner is reverified", async () => {
    await save(); now += offlineLifetime - 1000;
    await verifyOfflineOwner({ ...me, user: { ...user, display_name: "Alex updated" } });
    now += 1000;
    expect(await readOffline()).toMatchObject({ ownerName: "Alex updated", tasks: {} });
  });

  it("queues only changed fields, preserves explicit deadline removal and removes no-op changes", async () => {
    await save();
    await queueTaskEdit(user.id, task.id, { title: task.title, description: "Revised introduction", due_at: null, status: task.status, priority: task.priority, blocker_note: "" });
    expect((await row())?.changes).toEqual({ description: "Revised introduction", due_at: null });
    expect((await row())?.mutationId).toBeTruthy();
    await queueTaskEdit(user.id, task.id, { title: task.title, description: task.description, due_at: task.due_at });
    expect((await row())?.changes).toEqual({}); expect((await row())?.mutationId).toBeUndefined();
  });

  it("keeps blocker note and status consistent without queuing stale blocker text for an unblocked task", () => {
    const blocked = { ...task, status: "blocked" as const, blocker_note: "Waiting for source" };
    expect(changedFields(blocked, { blocker_note: "Waiting for tutor" })).toEqual({ blocker_note: "Waiting for tutor", status: "blocked" });
    expect(changedFields(blocked, { status: "in_progress", blocker_note: "Old blocker" })).toEqual({ status: "in_progress" });
  });

  it("protects pending changes from replacing the cached base and refuses archived copies", async () => {
    await save(); await queueTaskEdit(user.id, task.id, { title: "Saved locally" });
    await expect(keepTaskOffline(me, { ...task, title: "New server title" }, "Studio team")).rejects.toThrow("Sync or discard");
    expect((await row())?.changes.title).toBe("Saved locally");
    await expect(keepTaskOffline(me, { ...task, id: "archived", archived_at: task.updated_at }, "Studio team")).rejects.toThrow("Archived");
  });

  it("does not let a late response for an old mutation erase a newer local edit", async () => {
    await save(); await queueTaskEdit(user.id, task.id, { title: "First draft" });
    const first = (await row())!.mutationId!;
    await queueTaskEdit(user.id, task.id, { title: "Second draft" });
    const second = (await row())!.mutationId!;
    expect(second).not.toBe(first);
    await recordSyncResult(user.id, task.id, first, { task: { ...task, title: "First draft", updated_at: "2026-10-02T01:00:00Z" } });
    await recordSyncResult(user.id, task.id, first, { remove: true });
    expect(await row()).toMatchObject({ base: { title: task.title }, changes: { title: "Second draft" }, mutationId: second });
  });

  it("rebases only selected conflict fields and retains unselected current server values", async () => {
    await save(); await queueTaskEdit(user.id, task.id, { title: "Local title", description: "Local description", priority: "urgent", due_at: null });
    const before = (await row())!;
    const current = { ...task, title: "Server title", description: "Server description", priority: "high" as const, due_at: "2026-10-04T00:00:00Z", updated_at: "2026-10-02T01:00:00Z" };
    await recordSyncResult(user.id, task.id, before.mutationId!, { conflict: current });
    await resolveOfflineConflict(user.id, task.id, ["title"]);
    const resolved = (await row())!;
    expect(resolved.base).toEqual(current); expect(resolved.changes).toEqual({ title: "Local title" });
    expect(resolved.mutationId).not.toBe(before.mutationId); expect(resolved.conflict).toBeUndefined();
    expect({ ...resolved.base, ...resolved.changes }).toMatchObject({ title: "Local title", description: "Server description", priority: "high", due_at: current.due_at });
  });

  it("accepts every server value without another mutation when no conflict field is selected", async () => {
    await save(); await queueTaskEdit(user.id, task.id, { title: "Local title" });
    const pending = (await row())!;
    await recordSyncResult(user.id, task.id, pending.mutationId!, { conflict: { ...task, title: "Server title" } });
    await resolveOfflineConflict(user.id, task.id, []);
    expect(await row()).toMatchObject({ base: { title: "Server title" }, changes: {} });
    expect((await row())?.mutationId).toBeUndefined();
  });

  it("removes revoked task access and clears every device copy on request", async () => {
    await save(); await queueTaskEdit(user.id, task.id, { title: "Pending" });
    await recordSyncResult("other", task.id, (await row())!.mutationId!, { remove: true });
    expect(await row()).toBeDefined();
    await recordSyncResult(user.id, task.id, (await row())!.mutationId!, { remove: true });
    expect(await row()).toBeUndefined();
    await keepTaskOffline(me, task, "Studio team"); await clearOffline();
    expect(await readOffline()).toBeUndefined();
  });
});
