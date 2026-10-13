import { useState } from "react";
import { Link } from "react-router-dom";
import type { Me, Task } from "../api/types";
import { enableOffline, keepTaskOffline } from "../app/offlineTasks";
import { Button, Panel } from "./UI";
import { errorMessage } from "../api/client";

export default function KeepTaskOffline({ me, task, projectName, readOnly }: { me: Me; task: Task; projectName: string; readOnly: boolean }) {
  const [message, setMessage] = useState(""); const [busy, setBusy] = useState(false);
  const keep = async () => {
    setBusy(true);
    try { await enableOffline(me); await keepTaskOffline(me, task, projectName); setMessage("Task copy saved on this device. Open Offline tasks to edit it without a connection."); }
    catch (value) { setMessage(errorMessage(value)); }
    finally { setBusy(false); }
  };
  return <Panel><h3>Offline task copy</h3><p>Keep this task on this device for offline editing. Copies and pending edits expire after 24 hours and are cleared when you sign out.</p>
    <div className="row-actions"><Button variant="secondary" disabled={busy || readOnly} onClick={() => void keep()}>{busy ? "Saving copy…" : "Keep this task offline"}</Button><Link className="button button--quiet" to="/app/offline/">Open offline tasks</Link></div>
    {message && <p role="status">{message}</p>}</Panel>;
}
