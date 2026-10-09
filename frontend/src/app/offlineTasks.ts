import type { Me, Task, TaskPriority, TaskStatus } from "../api/types";

export const offlineLifetime = 24 * 60 * 60 * 1000;
export interface OfflineChanges { title?: string; description?: string; priority?: TaskPriority; due_at?: string | null; status?: TaskStatus; blocker_note?: string }
export interface OfflineTask { base: Task; projectName: string; changes: OfflineChanges; mutationId?: string; conflict?: Task; error?: string; cachedAt: number }
export interface OfflineWorkspace { ownerId: string; ownerName: string; verifiedAt: number; tasks: Record<string, OfflineTask> }
const DB = "studycrew-offline-v1", STORE = "workspace", KEY = "current";

function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB, 1);
    request.onupgradeneeded = () => { if (!request.result.objectStoreNames.contains(STORE)) request.result.createObjectStore(STORE); };
    request.onerror = () => reject(new Error("Offline storage is unavailable on this device."));
    request.onsuccess = () => { const result = request.result; result.onversionchange = () => result.close(); resolve(result); };
  });
}

async function change<T>(operation: (workspace: OfflineWorkspace | undefined) => { workspace?: OfflineWorkspace; result: T }, notify = true): Promise<T> {
  const db = await database();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite"), store = tx.objectStore(STORE);
    let result: T;
    const request = store.get(KEY);
    request.onsuccess = () => {
      try {
        const raw = request.result as OfflineWorkspace | undefined;
        const workspace = raw && Date.now() - raw.verifiedAt < offlineLifetime ? raw : undefined;
        if (workspace) for (const [id, task] of Object.entries(workspace.tasks)) if (Date.now() - task.cachedAt >= offlineLifetime) delete workspace.tasks[id];
        const updated = operation(workspace); result = updated.result;
        if (updated.workspace) store.put(updated.workspace, KEY); else store.delete(KEY);
      } catch (value) { tx.abort(); reject(value); }
    };
    tx.oncomplete = () => { db.close(); if (notify) window.dispatchEvent(new Event("studycrew:offline-changed")); resolve(result); };
    tx.onerror = () => { db.close(); reject(new Error("Your offline copy could not be saved. Check device storage.")); };
    tx.onabort = () => db.close();
  });
}

export async function readOffline(): Promise<OfflineWorkspace | undefined> {
  // Readwrite allows expired private copies to be removed in the same transaction.
  return change(workspace => ({ workspace, result: workspace }), false);
}

export async function enableOffline(me: Me) {
  return change(workspace => ({ workspace: workspace?.ownerId === me.user.id ? { ...workspace, verifiedAt: Date.now(), ownerName: me.user.display_name } :
    { ownerId: me.user.id, ownerName: me.user.display_name, verifiedAt: Date.now(), tasks: {} }, result: undefined }));
}

export async function verifyOfflineOwner(me: Me) {
  return change(workspace => ({ workspace: workspace?.ownerId === me.user.id ? { ...workspace, ownerName: me.user.display_name, verifiedAt: Date.now() } : undefined, result: undefined }), false);
}

export async function verifyOfflineIdentity(userId: string) {
  return change(workspace => ({ workspace: workspace?.ownerId === userId ? workspace : undefined, result: undefined }));
}

export async function clearOffline() { return change(() => ({ result: undefined })); }

export async function keepTaskOffline(me: Me, task: Task, projectName: string) {
  return change(workspace => {
    if (workspace?.ownerId !== me.user.id) throw new Error("Enable offline task copies first.");
    if (task.archived_at) throw new Error("Archived tasks cannot be edited offline.");
    const existing = workspace.tasks[task.id];
    if (!existing && Object.keys(workspace.tasks).length >= 200) throw new Error("This device can keep up to 200 task copies. Remove a copy first.");
    if (existing?.mutationId) throw new Error("Sync or discard the saved changes before replacing this copy.");
    workspace.tasks[task.id] = { base: structuredClone(task), projectName, changes: {}, cachedAt: Date.now() };
    return { workspace, result: undefined };
  });
}

export function changedFields(base: Task, values: OfflineChanges): OfflineChanges {
  const changes: OfflineChanges = {};
  for (const key of Object.keys(values) as (keyof OfflineChanges)[]) if (values[key] !== base[key]) Object.assign(changes, { [key]: values[key] });
  if (changes.blocker_note !== undefined && changes.status === undefined) changes.status = values.status ?? base.status;
  if (changes.status && changes.status !== "blocked") delete changes.blocker_note;
  return changes;
}

export async function queueTaskEdit(ownerId: string, taskId: string, values: OfflineChanges) {
  return change(workspace => {
    if (workspace?.ownerId !== ownerId || !workspace.tasks[taskId]) throw new Error("This task copy has expired. Reconnect and save a new copy.");
    const row = workspace.tasks[taskId];
    const changes = changedFields(row.base, values);
    if (Object.keys(changes).length && !row.mutationId && Object.values(workspace.tasks).filter(task => task.mutationId).length >= 50) throw new Error("Sync the pending changes first; this device keeps up to 50 pending edits.");
    row.changes = changes; row.mutationId = Object.keys(changes).length ? crypto.randomUUID() : undefined;
    row.conflict = undefined; row.error = undefined;
    return { workspace, result: undefined };
  });
}

export async function recordSyncResult(ownerId: string, taskId: string, mutationId: string, result: { task?: Task; conflict?: Task; error?: string; remove?: boolean }) {
  return change(workspace => {
    const row = workspace?.ownerId === ownerId ? workspace.tasks[taskId] : undefined;
    if (!workspace || !row || row.mutationId !== mutationId) return { workspace, result: undefined };
    if (result.remove) delete workspace.tasks[taskId];
    else if (result.task) workspace.tasks[taskId] = { base: result.task, projectName: row.projectName, changes: {}, cachedAt: Date.now() };
    else { row.conflict = result.conflict; row.error = result.error; }
    return { workspace, result: undefined };
  });
}

export async function resolveOfflineConflict(ownerId: string, taskId: string, keepFields: (keyof OfflineChanges)[]) {
  return change(workspace => {
    const row = workspace?.ownerId === ownerId ? workspace.tasks[taskId] : undefined;
    if (!workspace || !row?.conflict) throw new Error("Refresh the conflict before choosing changes.");
    const chosen = Object.fromEntries(keepFields.filter(key => key in row.changes).map(key => [key, row.changes[key]])) as OfflineChanges;
    if (keepFields.includes("blocker_note")) chosen.status = "blocked";
    row.base = row.conflict; row.changes = changedFields(row.base, chosen); row.conflict = undefined; row.error = undefined;
    row.mutationId = Object.keys(row.changes).length ? crypto.randomUUID() : undefined; row.cachedAt = Date.now();
    return { workspace, result: undefined };
  });
}

export async function removeOfflineTask(ownerId: string, taskId: string) {
  return change(workspace => { if (workspace?.ownerId === ownerId) delete workspace.tasks[taskId]; return { workspace, result: undefined }; });
}
