import { useEffect } from "react";
import { clearOffline, readOffline } from "../app/offlineTasks";
import { syncOfflineTasks } from "../api/offline";

export default function OfflineCoordinator() {
  useEffect(() => {
    if ("serviceWorker" in navigator) void navigator.serviceWorker.register("/service-worker.js").catch(() => undefined);
    let timer: ReturnType<typeof setTimeout>;
    const sync = () => { if (navigator.onLine) void syncOfflineTasks().catch(() => undefined); };
    const changed = () => { clearTimeout(timer); timer = setTimeout(() => { void readOffline().then(workspace => {
      if (workspace && Object.values(workspace.tasks).some(row => row.mutationId && !row.conflict && !row.error)) sync();
    }).catch(() => undefined); }, 600); };
    const expired = () => { void clearOffline().catch(() => undefined); };
    window.addEventListener("online", sync); window.addEventListener("studycrew:offline-changed", changed);
    window.addEventListener("studycrew:session-expired", expired); changed();
    return () => { clearTimeout(timer); window.removeEventListener("online", sync); window.removeEventListener("studycrew:offline-changed", changed); window.removeEventListener("studycrew:session-expired", expired); };
  }, []);
  return null;
}
