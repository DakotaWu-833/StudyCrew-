import { useEffect, useState } from "react";
import { clearUserDrafts, pruneDrafts } from "../app/drafts";
import { clearOffline, verifyOfflineIdentity } from "../app/offlineTasks";
import { Link } from "react-router-dom";

export default function BrowserReadiness({ userId }: { userId?: string }) {
  const [offline, setOffline] = useState(!navigator.onLine);
  useEffect(() => {
    pruneDrafts();
    if (userId) void verifyOfflineIdentity(userId).catch(() => undefined);
    if ("serviceWorker" in navigator) void navigator.serviceWorker.register("/service-worker.js").catch(() => undefined);
    const update = () => setOffline(!navigator.onLine);
    const logout = (event: Event) => { const target = event.target; if (target instanceof HTMLFormElement && new URL(target.action).pathname === "/account/logout/") {
      event.preventDefault(); if (userId) clearUserDrafts(userId);
      void clearOffline().catch(() => undefined).finally(() => HTMLFormElement.prototype.submit.call(target));
    } };
    window.addEventListener("online", update); window.addEventListener("offline", update); document.addEventListener("submit", logout);
    return () => { window.removeEventListener("online", update); window.removeEventListener("offline", update); document.removeEventListener("submit", logout); };
  }, [userId]);
  return offline ? <div className="notice" role="status">You are offline. <Link to="/app/offline/">Edit your saved task copies</Link> and sync after reconnecting. Long text drafts stay on this device.</div> : null;
}
