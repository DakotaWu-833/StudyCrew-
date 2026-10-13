import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { accountApi } from "../api/resources";
import { errorMessage } from "../api/client";
import { syncOfflineTasks } from "../api/offline";
import type { Me, TaskPriority, TaskStatus } from "../api/types";
import { clearOffline, enableOffline, queueTaskEdit, readOffline, removeOfflineTask, resolveOfflineConflict, verifyOfflineOwner, type OfflineChanges, type OfflineTask, type OfflineWorkspace } from "../app/offlineTasks";
import { parseOptionalDateTime, toDateTimeLocal, titleCase } from "../app/format";
import { Button, EmptyState, Field, FloatingPanel, Loading, Panel } from "../components/UI";
import "./offline-tasks.css";

export default function OfflineTasksPage() {
  const [workspace, setWorkspace] = useState<OfflineWorkspace>();
  const [me, setMe] = useState<Me>();
  const [online, setOnline] = useState(navigator.onLine);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<OfflineTask>();
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        if (navigator.onLine) { const current = await accountApi.me(); await verifyOfflineOwner(current); if (cancelled) return; setMe(current); }
        const stored = await readOffline(); if (!cancelled) { setWorkspace(stored); setLoading(false); }
      } catch (value) { if (!cancelled) { setError(errorMessage(value)); setLoading(false); } }
    };
    const local = () => { void readOffline().then(value => { if (!cancelled) setWorkspace(value); }).catch(value => { if (!cancelled) setError(errorMessage(value)); }); };
    const connection = () => { setOnline(navigator.onLine); void load(); };
    window.addEventListener("online", connection); window.addEventListener("offline", connection); window.addEventListener("studycrew:offline-changed", local);
    void load();
    return () => { cancelled = true; window.removeEventListener("online", connection); window.removeEventListener("offline", connection); window.removeEventListener("studycrew:offline-changed", local); };
  }, []);
  const action = async (operation: () => Promise<unknown>) => { setBusy(true); setError(""); try { await operation(); setWorkspace(await readOffline()); } catch (value) { setError(errorMessage(value)); } finally { setBusy(false); } };
  const edit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (!workspace || !editing) return;
    const data = new FormData(event.currentTarget); const due_at = parseOptionalDateTime(String(data.get("due_at")));
    if (due_at === undefined) { setError("Choose a valid due date and time."); return; }
    const values: OfflineChanges = { title: String(data.get("title")), description: String(data.get("description")), priority: String(data.get("priority")) as TaskPriority,
      due_at, status: String(data.get("status")) as TaskStatus, blocker_note: String(data.get("blocker_note")) };
    if (values.status === "blocked" && (values.blocker_note?.trim().length ?? 0) < 3) { setError("Describe the blocker using at least 3 characters."); return; }
    void action(async () => { await queueTaskEdit(workspace.ownerId, editing.base.id, values); setEditing(undefined); });
  };
  if (loading) return <Loading label="Opening saved task copies…" />;
  return <div className="page-stack offline-page"><div className="page-heading"><div><h2>Offline tasks</h2><p>{online ? "Connected · pending changes sync automatically" : "Offline · edits stay on this device until you reconnect"}</p></div><Link to="/app/" className="button button--quiet">Return to workspace</Link></div>
    {error && <p className="notice notice--error" role="alert">{error}</p>}
    <Panel><p>Only tasks you choose are saved on this device. Copies and pending edits expire after 24 hours and are cleared when you sign out. Keep copies from each task's detail page while connected.</p>
      {workspace ? <><p>Saved for <strong>{workspace.ownerName}</strong> · {Object.keys(workspace.tasks).length} task copies</p><div className="row-actions"><Button variant="secondary" disabled={!online || busy} onClick={() => void action(syncOfflineTasks)}>Sync now</Button><Button variant="quiet" disabled={busy} onClick={() => void action(clearOffline)}>Clear all device copies</Button></div></> : me && online ? <Button disabled={busy} onClick={() => void action(() => enableOffline(me))}>Enable offline task copies</Button> : <p>Reconnect and sign in to choose tasks for offline use.</p>}
    </Panel>
    {workspace && !Object.keys(workspace.tasks).length && <EmptyState title="No saved tasks">Open a task while connected and choose Keep this task offline.</EmptyState>}
    {workspace && Object.values(workspace.tasks).map(row => <Panel key={row.base.id}><div className="section-heading"><div><h3>{row.changes.title ?? row.base.title}</h3><p className="muted">{row.projectName} · {row.conflict ? "Conflict needs review" : row.error ? "Sync needs attention" : row.mutationId ? "Pending sync" : "Saved copy"}</p></div></div>
      <p className="prose">{row.changes.description ?? row.base.description}</p>
      {row.error && <p role="alert" className="notice notice--error">{row.error} Your local changes are retained.</p>}
      {row.conflict && <OfflineConflict row={row} busy={busy} resolve={fields => action(() => resolveOfflineConflict(workspace.ownerId, row.base.id, fields))} />}
      <div className="row-actions"><Button variant="secondary" disabled={busy || Boolean(row.conflict)} onClick={() => { setDirty(false); setEditing(row); }}>Edit saved task</Button><Button variant="quiet" disabled={busy} onClick={() => void action(() => removeOfflineTask(workspace.ownerId, row.base.id))}>Remove device copy</Button></div>
    </Panel>)}
    {editing && <FloatingPanel title="Edit saved task" busy={busy} dirty={dirty} onDismiss={() => setEditing(undefined)}><form className="form-grid" onSubmit={edit} onChange={() => setDirty(true)}>
      <Field label="Title"><input name="title" required minLength={3} maxLength={120} defaultValue={editing.changes.title ?? editing.base.title} /></Field>
      <Field label="Description"><textarea name="description" maxLength={4000} rows={4} defaultValue={editing.changes.description ?? editing.base.description} /></Field>
      <Field label="Priority"><select name="priority" defaultValue={editing.changes.priority ?? editing.base.priority}>{["low", "medium", "high", "urgent"].map(value => <option key={value} value={value}>{titleCase(value)}</option>)}</select></Field>
      <Field label="Due date"><input name="due_at" type="datetime-local" defaultValue={toDateTimeLocal("due_at" in editing.changes ? editing.changes.due_at ?? null : editing.base.due_at)} /></Field>
      <Field label="Status" hint="The server checks your permission, dependencies and required reviews before applying a change."><select name="status" defaultValue={editing.changes.status ?? editing.base.status}>{["todo", "in_progress", "blocked", "done"].map(value => <option key={value} value={value}>{titleCase(value)}</option>)}</select></Field>
      <Field label="Blocker note"><textarea name="blocker_note" rows={2} maxLength={500} defaultValue={editing.changes.blocker_note ?? editing.base.blocker_note} /></Field>
      {error && <p className="form-error" role="alert">{error}</p>}<Button type="submit" disabled={busy}>Save on this device</Button>
    </form></FloatingPanel>}
  </div>;
}

function OfflineConflict({ row, busy, resolve }: { row: OfflineTask; busy: boolean; resolve: (fields: (keyof OfflineChanges)[]) => Promise<void> }) {
  const [keep, setKeep] = useState<(keyof OfflineChanges)[]>([]);
  const fields = Object.keys(row.changes) as (keyof OfflineChanges)[];
  return <div className="offline-conflict"><h4>The task changed while you were offline</h4><p>Choose each local change to keep. Unselected fields use the current server value.</p><div className="table-scroll"><table><thead><tr><th>Keep local</th><th>Field</th><th>Your change</th><th>Current server value</th></tr></thead><tbody>{fields.map(field => <tr key={field}><td><input type="checkbox" aria-label={`Keep local ${field.replaceAll("_", " ")}`} checked={keep.includes(field)} onChange={event => setKeep(previous => event.target.checked ? [...previous, field] : previous.filter(value => value !== field))} /></td><th>{titleCase(field)}</th><td>{String(row.changes[field] ?? "No value")}</td><td>{String(row.conflict?.[field] ?? "No value")}</td></tr>)}</tbody></table></div><Button disabled={busy} variant="secondary" onClick={() => void resolve(keep)}>Apply these choices</Button></div>;
}
