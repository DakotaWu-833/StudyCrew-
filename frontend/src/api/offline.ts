import { apiFetch, APIError, jsonBody } from "./client";
import type { Task } from "./types";
import { accountApi } from "./resources";
import { readOffline, recordSyncResult, verifyOfflineOwner, type OfflineChanges } from "../app/offlineTasks";

export const offlineApi = {
  sync: (taskId: string, mutationId: string, expected_updated_at: string, changes: OfflineChanges, ownerId: string) =>
    apiFetch<{ task: Task; duplicate: boolean }>(`/api/v1/offline/tasks/${taskId}/sync/`, { method: "POST", ...jsonBody({ expected_user_id: ownerId, mutation_id: mutationId, expected_updated_at, changes }) }),
};
let synchronizing = false;
export async function syncOfflineTasks() {
  if (synchronizing || !navigator.onLine) return;
  synchronizing = true;
  try {
    const me = await accountApi.me(); await verifyOfflineOwner(me);
    const workspace = await readOffline(); if (!workspace || workspace.ownerId !== me.user.id) return;
    for (const row of Object.values(workspace.tasks)) {
      if (!navigator.onLine || !row.mutationId || row.conflict) continue;
      try {
        const result = await offlineApi.sync(row.base.id, row.mutationId, row.base.updated_at, row.changes, workspace.ownerId);
        await recordSyncResult(workspace.ownerId, row.base.id, row.mutationId, { task: result.task });
      } catch (error) {
        if (error instanceof APIError && [401, 403, 404].includes(error.status)) {
          await recordSyncResult(workspace.ownerId, row.base.id, row.mutationId, { remove: true });
        } else if (error instanceof APIError && error.status === 409 && error.current) {
          await recordSyncResult(workspace.ownerId, row.base.id, row.mutationId, { conflict: error.current });
        } else if (error instanceof APIError) {
          await recordSyncResult(workspace.ownerId, row.base.id, row.mutationId, { error: error.message });
        } else { break; } // Transport uncertainty retains the exact idempotent edit for retry.
      }
    }
  } finally { synchronizing = false; }
}
