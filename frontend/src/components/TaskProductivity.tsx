import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { productivityApi as api, type ManualTimeInput, type ScheduleInput, type TimeEntry } from "../api/productivity";
import { errorMessage } from "../api/client";
import { formatDate, parseOptionalDateTime, toDateTimeLocal, today } from "../app/format";
import { Button, ConfirmAction, ErrorState, Field, Loading, Panel } from "./UI";
import "../pages/productivity.css";

export const hours = (seconds: number) => `${(seconds / 3600).toFixed(2)} h`;
function clock(seconds: number) {
  const value = Math.max(0, Math.min(86400, seconds));
  return `${String(Math.floor(value / 3600)).padStart(2, "0")}:${String(Math.floor(value / 60) % 60).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
}

export default function TaskProductivity({ projectId, taskId, readOnly = false }: { projectId: string; taskId: string; readOnly?: boolean }) {
  const client = useQueryClient();
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<TimeEntry | null>(null);
  const [notice, setNotice] = useState("");
  const [localError, setLocalError] = useState("");
  const [timerNote, setTimerNote] = useState("");
  const [tick, setTick] = useState(Date.now());
  const overview = useQuery({ queryKey: ["productivity", projectId, taskId, page], queryFn: () => api.overview(projectId, taskId, page), enabled: Boolean(projectId && taskId), refetchInterval: query => query.state.data?.active_timer ? 5000 : false });
  const mutation = useMutation({
    mutationFn: (action: () => Promise<unknown>) => action(),
    onSuccess: async () => {
      setEditing(null); setTimerNote(""); setLocalError(""); setNotice("Saved.");
      await Promise.all([client.invalidateQueries({ queryKey: ["productivity"] }), client.invalidateQueries({ queryKey: ["workload", projectId] }), client.invalidateQueries({ queryKey: ["tasks", projectId] }), client.invalidateQueries({ queryKey: ["campus-todos"] })]);
    },
  });
  const running = overview.data?.active_timer;
  useEffect(() => { if (!running) return; const timer = setInterval(() => setTick(Date.now()), 1000); return () => clearInterval(timer); }, [running?.id]);
  function run(action: () => Promise<unknown>) { setNotice(""); setLocalError(""); mutation.mutate(action); }
  function saveTime(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const stamp = parseOptionalDateTime(String(data.get("started_at")));
    if (!stamp) { setLocalError("Choose a valid time in your profile timezone."); return; }
    const input: ManualTimeInput = { started_at: stamp, minutes: Number(data.get("minutes")), note: String(data.get("note")) };
    run(() => editing ? api.correct(projectId, taskId, editing, input) : api.addManual(projectId, taskId, input));
  }
  function schedule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const input: ScheduleInput = { frequency: String(data.get("frequency")) as ScheduleInput["frequency"], interval: Number(data.get("interval")), timezone_name: String(data.get("timezone_name")), start_local: String(data.get("start_local")), until_date: String(data.get("until_date")), occurrence_limit: Number(data.get("occurrence_limit")), lead_days: Number(data.get("lead_days")) };
    run(() => api.createSchedule(projectId, taskId, input));
  }
  if (overview.isPending) return <Panel><Loading label="Loading time and recurring tasks" /></Panel>;
  if (overview.error || !overview.data) return <Panel><ErrorState error={overview.error} retry={() => void overview.refetch()} /></Panel>;
  const data = overview.data;
  const locked = readOnly || data.read_only;
  const busy = mutation.isPending;
  const onThisTask = running?.task_id === taskId && running?.project_id === projectId;
  const elapsed = running ? Math.floor((tick - new Date(running.started_at).getTime()) / 1000) : 0;
  const activeSchedule = data.schedules.some(item => !item.stopped_at);
  const defaultStart = toDateTimeLocal(new Date(Date.now() + 7 * 86400000).toISOString());
  return <div className="page-stack productivity">
    {(notice || localError || mutation.error) && <p className="notice" role={localError || mutation.error ? "alert" : "status"}>{localError || (mutation.error ? errorMessage(mutation.error) : notice)}</p>}
    <Panel><h3>Time spent</h3><p>Team recorded time: <strong>{hours(data.actual_seconds)}</strong> · Yours: <strong>{hours(data.my_seconds)}</strong> · <Link to={`/app/projects/${projectId}/workload`}>View team workload</Link></p>
      <p className="muted">Time is self-recorded. Your notes stay private. Running timers are excluded from totals. Completed timer records are capped at 24 hours.</p>
      {running ? <div className="productivity-timer"><strong className="productivity-clock" aria-label="Elapsed timer time">{clock(elapsed)}</strong><p>{onThisTask ? "Timer running on this task." : running.accessible ? <>Timer running on <Link to={`/app/projects/${running.project_id}/tasks/${running.task_id}`}>{running.title}</Link>.</> : "Your timer belongs to a project you can no longer access."}</p>{elapsed >= 86400 && <p>Recorded duration will be capped at 24 hours. Correct it if needed.</p>}
        {onThisTask && !locked && <><Field label="Private timer note"><input value={timerNote} onChange={event => setTimerNote(event.target.value)} maxLength={500} disabled={busy} /></Field><Button disabled={busy} onClick={() => run(() => api.stopTimer(projectId, taskId, timerNote))}>Stop and record time</Button></>}
        <ConfirmAction busy={busy} triggerLabel="Discard running timer" confirmLabel="Discard timer" message="Discard this running timer without recording any time?" onConfirm={() => run(api.discardTimer)} />
      </div> : !locked && <Button disabled={busy} onClick={() => run(() => api.startTimer(projectId, taskId))}>Start timer</Button>}
      {locked && <p className="notice">Time records are read-only because this task or project is archived.</p>}
      {!locked && <details open={Boolean(editing)}><summary>{editing ? "Correct your time record" : "Add time manually"}</summary><form className="form-grid productivity-form" key={editing?.id ?? "new-time"} onSubmit={saveTime}><fieldset disabled={busy} className="form-grid"><legend>{editing ? "Correct recorded work" : "Record work already completed"}</legend>
        <Field label={`Started at (${data.timezone_name})`}><input type="datetime-local" name="started_at" defaultValue={toDateTimeLocal(editing?.started_at ?? new Date(Date.now() - 3600000).toISOString())} required /></Field>
        <Field label="Minutes (1–1440)"><input type="number" name="minutes" min={1} max={1440} defaultValue={editing ? Math.max(1, Math.round(editing.seconds / 60)) : 60} required /></Field>
        <Field label="Private note"><textarea name="note" defaultValue={editing?.note ?? ""} maxLength={500} /></Field>
        <div className="form-actions"><Button>{editing ? "Save correction" : "Record time"}</Button>{editing && <Button type="button" variant="quiet" onClick={() => setEditing(null)}>Cancel correction</Button>}</div>
      </fieldset></form></details>}
      <h4>Your time records</h4>{!data.entries.length && <p>No completed time records yet.</p>}
      {data.entries.map(entry => <article className="productivity-entry" key={entry.id}><div><strong>{hours(entry.seconds)}</strong> · {entry.source} · {formatDate(entry.started_at)}{entry.corrected_at && <span> · corrected</span>}{entry.capped && <span> · capped at 24 hours</span>}<p className="prose">{entry.note}</p></div>{!locked && <div className="form-actions"><Button variant="secondary" disabled={busy} onClick={() => { setEditing(entry); setLocalError(""); }}>Correct</Button><ConfirmAction busy={busy} triggerLabel="Discard record" confirmLabel="Discard time record" message="Remove this time record from your totals?" onConfirm={() => run(() => api.discard(projectId, taskId, entry))} /></div>}</article>)}
      {data.pages > 1 && <div className="form-actions"><Button variant="secondary" disabled={busy || page === 1} onClick={() => setPage(page - 1)}>Previous records</Button><span>Page {data.page} of {data.pages}</span><Button variant="secondary" disabled={busy || page === data.pages} onClick={() => setPage(page + 1)}>Next records</Button></div>}
    </Panel>
    <Panel><h3>Recurring tasks</h3><p>Create independent copies of this task on a weekly or monthly schedule. Titles, descriptions, estimates, tags and checklist text are saved when the schedule is created. Checklist completion, review, dependencies, parent and official deadlines are reset. Only current assignees are copied.</p>
      <p className="muted">Month-end dates use the last available day, then return to the original day in longer months. Daylight-saving gaps move forward by the gap; repeated times use the earlier occurrence. Archiving the source or project, or removing its author, stops generation.</p>
      {data.schedules.map(item => <article className="productivity-entry" key={item.id}><div><strong>Every {item.interval} {item.frequency === "weekly" ? "week(s)" : "month(s)"}</strong> · {item.timezone_name}<p>{item.generated_count} / {item.occurrence_limit} generated · ends {item.until_date}{item.stopped_at ? ` · ${item.stop_reason}` : ` · next deadline ${formatDate(item.next_due_at)}`}</p></div>{!item.stopped_at && item.can_stop && <ConfirmAction busy={busy} triggerLabel="Stop schedule" confirmLabel="Stop recurring tasks" message="Stop creating future tasks? Copies already created will remain in the project." onConfirm={() => run(() => api.stopSchedule(projectId, taskId, item.id))} />}</article>)}
      {!locked && !activeSchedule && <details><summary>Create a recurring schedule</summary><form className="form-grid productivity-form" onSubmit={schedule}><fieldset className="form-grid" disabled={busy}><legend>Future task deadlines</legend>
        <div className="productivity-form-grid"><Field label="Frequency"><select name="frequency" defaultValue="weekly"><option value="weekly">Weekly</option><option value="monthly">Monthly</option></select></Field><Field label="Repeat every (1–12)"><input type="number" name="interval" defaultValue={1} min={1} max={12} required /></Field></div>
        <Field label="Schedule timezone"><input name="timezone_name" defaultValue={data.timezone_name} maxLength={64} required /></Field><Field label="First generated task deadline (local time)"><input type="datetime-local" name="start_local" defaultValue={defaultStart} required /></Field>
        <div className="productivity-form-grid"><Field label="End date (within ten years)"><input type="date" name="until_date" defaultValue={today(365)} required /></Field><Field label="Maximum copies (1–520)"><input type="number" name="occurrence_limit" defaultValue={12} min={1} max={520} required /></Field></div>
        <Field label="Create each task this many days before its deadline (0–30)"><input type="number" name="lead_days" defaultValue={7} min={0} max={30} required /></Field><Button>Create schedule</Button>
      </fieldset></form></details>}
    </Panel>
  </div>;
}
