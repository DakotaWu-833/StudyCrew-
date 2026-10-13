import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { coordinationApi, type CalendarEvent, type CalendarSubscription } from "../api/coordination";
import { projectApi } from "../api/resources";
import { errorMessage } from "../api/client";
import { Button, ConfirmAction, EmptyState, ErrorState, Field, Loading, Panel } from "../components/UI";
import "../coordination.css";

function dateString(value: Date) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

function dateOnly(value: string) {
  const [year = 1970, month = 1, day = 1] = value.split("-").map(Number);
  return new Date(year, month - 1, day, 12);
}
function shiftDay(value: string, days: number) {
  const result = dateOnly(value); result.setDate(result.getDate() + days); return dateString(result);
}
function mondayOf(value: string) { return shiftDay(value, -((dateOnly(value).getDay() + 6) % 7)); }
const labels: Record<CalendarEvent["kind"], string> = {
  meeting: "Meeting", task: "Task deadline", task_official: "Official task deadline", project: "Project deadline",
  submission_internal: "Internal submission", submission_official: "Official submission", milestone: "Milestone",
};

export default function CalendarPage() {
  const { projectId } = useParams();
  const [searchParams] = useSearchParams();
  const client = useQueryClient();
  const [view, setView] = useState<"month" | "week">("month");
  const [month, setMonth] = useState(() => dateString(new Date()).slice(0, 7));
  const [weekStart, setWeekStart] = useState(() => mondayOf(dateString(new Date())));
  const [selectedProject, setSelectedProject] = useState(projectId ?? searchParams.get("project") ?? "");
  const [feed, setFeed] = useState<CalendarSubscription | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const year = Number(month.slice(0, 4));
  const monthNumber = Number(month.slice(5, 7));
  const start = view === "week" ? weekStart : `${month}-01`;
  const end = view === "week" ? shiftDay(weekStart, 6) : dateString(new Date(year, monthNumber, 0, 12));
  const validRange = /^\d{4}-\d{2}-\d{2}$/.test(start) && /^\d{4}-\d{2}-\d{2}$/.test(end) && start >= "1900-01-01" && end <= "9998-12-31";
  const scope = projectId || selectedProject || undefined;
  const projects = useQuery({ queryKey: ["projects"], queryFn: projectApi.list });
  const calendar = useQuery({ queryKey: ["calendar", start, end, scope], queryFn: () => coordinationApi.calendar(start, end, scope), enabled: validRange });
  const subscriptions = useQuery({ queryKey: ["calendar-subscriptions"], queryFn: coordinationApi.subscriptions });
  const operation = useMutation({ mutationFn: async (action: () => Promise<unknown>) => action(), onSuccess: async () => { setError(""); await client.invalidateQueries({ queryKey: ["calendar-subscriptions"] }); }, onError: (value) => { setMessage(""); setError(errorMessage(value)); } });
  const busy = operation.isPending;
  const days = view === "week" ? 7 : new Date(year, monthNumber, 0, 12).getDate();
  const firstWeekday = view === "week" ? 0 : (new Date(year, monthNumber - 1, 1, 12).getDay() + 6) % 7;
  const timezone = calendar.data?.time_zone ?? "UTC";
  const formatter = new Intl.DateTimeFormat("en-CA", { timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit" });
  const timeFormatter = new Intl.DateTimeFormat(undefined, { timeZone: timezone, hour: "2-digit", minute: "2-digit" });
  const localDay = (value: string) => {
    const parts = formatter.formatToParts(new Date(value));
    const part = (name: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === name)?.value ?? "";
    return `${part("year")}-${part("month")}-${part("day")}`;
  };
  const eventsForDay = (day: string) => calendar.data?.events.filter((item) => localDay(item.starts_at) <= day && localDay(new Date(Date.parse(item.ends_at) - 1).toISOString()) >= day) ?? [];
  const movePeriod = (direction: number) => {
    if (view === "week") {
      const next = shiftDay(weekStart, direction * 7);
      setWeekStart(next); setMonth(shiftDay(next, 3).slice(0, 7));
    }
    else setMonth(dateString(new Date(year, monthNumber - 1 + direction, 1, 12)).slice(0, 7));
  };
  const changeView = (value: "month" | "week") => {
    if (value === "week") setWeekStart(mondayOf(`${month}-01`));
    setView(value);
  };
  const createSubscription = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const details = new FormData(event.currentTarget).get("details") === "on";
    operation.mutate(async () => { const value = await coordinationApi.subscribe(scope, details); setFeed(value); setMessage("Subscription created. Save its private link now; it is only shown once."); });
  };
  return <div className="page-stack coordination-page">
    <header className="page-heading"><div><p className="eyebrow">Plan your week</p><h1>{scope ? "Project calendar" : "My calendar"}</h1><p>Meetings, {scope ? "team task deadlines" : "your assigned task deadlines"} , milestones and internal or recorded official submission deadlines in one place.</p></div></header>
    {error && <p className="form-error" role="alert">{error}</p>}{message && <p className="success-message" role="status">{message}</p>}
    <Panel><div className="filter-bar"><Field label="View"><select value={view} onChange={(event) => changeView(event.target.value === "week" ? "week" : "month")}><option value="month">Month</option><option value="week">Week</option></select></Field>{view === "month" ? <Field label="Month"><input type="month" min="1900-01" max="9998-12" required value={month} onChange={(event) => setMonth(event.target.value)} /></Field> : <Field label="Week starting Monday"><input type="date" min="1900-01-01" max="9998-12-25" required value={weekStart} onChange={(event) => { if (event.target.value) { setWeekStart(mondayOf(event.target.value)); setMonth(event.target.value.slice(0, 7)); } }} /></Field>}{!projectId && <Field label="Calendar scope"><select value={selectedProject} onChange={(event) => setSelectedProject(event.target.value)}><option value="">All my active projects</option>{projects.data?.results.filter((item) => !item.archived_at).map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></Field>}<a className="button button--secondary" href={coordinationApi.calendarExportUrl(start, end, scope)} aria-disabled={!validRange} onClick={(event) => { if (!validRange) event.preventDefault(); }}>Download this {view} (.ics)</a></div>
      <div className="form-actions coord-calendar-navigation"><Button variant="secondary" disabled={!validRange || start <= "1900-01-07"} onClick={() => movePeriod(-1)}>Previous {view}</Button><strong>{start} to {end}</strong><Button variant="secondary" disabled={!validRange || end >= "9998-12-25"} onClick={() => movePeriod(1)}>Next {view}</Button></div>
      <p className="muted">Only projects where you are a current member appear. Times use {timezone}. Official deadlines are entered by the team and are not synced from the university. An export is a snapshot; a subscription refreshes in your calendar app.</p>
      {!projectId && projects.error && <ErrorState error={projects.error} retry={() => void projects.refetch()} />}
      {!validRange ? <p role="alert">Choose a valid {view} between 1900 and 9998.</p> : calendar.isLoading ? <Loading label="Loading your calendar…" /> : calendar.error ? <ErrorState error={calendar.error} retry={() => void calendar.refetch()} /> : <>
        {calendar.data?.truncated && <p role="alert">This range exceeds 1,000 events. Select a project or switch to a week to see every event.</p>}
        <div className="coord-calendar-scroll"><div className={`coord-calendar coord-calendar--${view}`} aria-label={`${start} to ${end} calendar`}>
          {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((label) => <div className="coord-calendar-dayname" key={label}>{label}</div>)}
          {Array.from({ length: firstWeekday }, (_, index) => <div className="coord-calendar-blank" key={`blank-${index}`} />)}
          {Array.from({ length: days }, (_, index) => shiftDay(start, index)).map((day) => <section aria-label={day} className="coord-calendar-cell" key={day}><strong>{view === "week" ? day.slice(5) : Number(day.slice(8))}</strong>{eventsForDay(day).map((item) => <Link className={`coord-calendar-event coord-calendar-event--${item.kind} ${item.cancelled ? "coord-calendar-event--cancelled" : ""}`} to={item.url} key={`${item.kind}-${item.id}`}><span>{timeFormatter.format(new Date(item.starts_at))} · {item.cancelled ? "Cancelled meeting" : labels[item.kind]}</span>{item.title}<small>{item.project_name}</small></Link>)}</section>)}
        </div></div>
        {!calendar.data?.events.length && <EmptyState title={`A clear ${view}`}>No meetings or relevant deadlines are scheduled for this {view}.</EmptyState>}
      </>}
    </Panel>
    <Panel><h2>Calendar subscriptions</h2><p>A subscription link grants read access without sign-in. Keep it private. By default, event names and locations are hidden. Revoking or rotating a link stops future access; it cannot erase copies already saved in another calendar app.</p>
      <form onSubmit={createSubscription} className="form-stack"><label className="checkbox-row"><input type="checkbox" name="details" /> Include project names, task/meeting titles, agendas and locations in this private feed</label><Button type="submit" disabled={busy || Boolean(projects.error)}>Create {scope ? "project" : "personal"} subscription</Button></form>
      {feed?.feed_url && <div className="coord-private-link"><Field label="Private subscription URL" hint="Copy this HTTPS URL into your calendar app's subscribe-by-URL option. It expires after one year."><input readOnly value={feed.feed_url} onFocus={(event) => event.currentTarget.select()} /></Field><Button variant="quiet" onClick={() => setFeed(null)}>Hide private URL</Button></div>}
      {subscriptions.isLoading ? <Loading label="Loading subscriptions…" /> : subscriptions.error ? <ErrorState error={subscriptions.error} retry={() => void subscriptions.refetch()} /> : !subscriptions.data?.subscriptions.length ? <EmptyState title="No subscriptions">Create a private feed to see updated events in your calendar app.</EmptyState> : <div className="coord-list">{subscriptions.data.subscriptions.map((row) => <article className="coord-card" key={row.id}><strong>{row.project_id ? projects.data?.results.find((project) => project.id === row.project_id)?.name ?? "Project subscription" : "Personal calendar"}</strong><p>{row.include_details ? "Detailed events" : "Private event labels"} · {row.revoked_at ? "Revoked" : new Date(row.expires_at) <= new Date() ? "Expired" : "Active"} · Expires {new Date(row.expires_at).toLocaleDateString()}</p>{!row.revoked_at && <div className="form-actions"><Button disabled={busy} variant="secondary" onClick={() => operation.mutate(async () => { const value = await coordinationApi.rotateSubscription(row.id); setFeed(value); setMessage("Old URL revoked. Copy the replacement private URL."); })}>Rotate URL</Button><ConfirmAction busy={busy} triggerLabel="Revoke" confirmLabel="Revoke subscription" message="Stop this subscription from refreshing? Existing saved copies may remain in other calendar apps." onConfirm={() => operation.mutate(async () => { await coordinationApi.revokeSubscription(row.id); setFeed(null); setMessage("Subscription revoked."); })} /></div>}</article>)}</div>}
    </Panel>
  </div>;
}
