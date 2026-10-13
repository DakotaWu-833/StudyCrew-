import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { operationsApi, type NotificationPreferences } from "../api/operations";
import { projectApi } from "../api/resources";
import { errorMessage } from "../api/client";
import ListPagination from "../components/ListPagination";
import { Button, EmptyState, ErrorState, Field, Loading, Panel, StatusBadge } from "../components/UI";

const options = [["in_app", "In-app notifications"], ["email", "Email notifications"], ["task_reminders", "Task, milestone and submission deadlines"], ["meeting_reminders", "Upcoming meetings"], ["assignments", "Task assignments"], ["mentions", "Comment mentions"], ["invitations", "Project invitations"], ["meeting_changes", "Meeting changes"]] as const;

function PreferenceForm({ preference }: { preference: NotificationPreferences }) {
  const cache = useQueryClient();
  const [message, setMessage] = useState("");
  const update = useMutation({ mutationFn: operationsApi.updatePreferences, onSuccess: () => { setMessage("Your notification preferences are saved."); void cache.invalidateQueries({ queryKey: ["notification-preferences"] }); } });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    const value = Object.fromEntries(options.map(([key]) => [key, form.has(key)])) as Partial<NotificationPreferences>;
    update.mutate({ ...value, digest: String(form.get("digest")) as NotificationPreferences["digest"], quiet_start: String(form.get("quiet_start")) || null, quiet_end: String(form.get("quiet_end")) || null });
  }
  return <form className="launch-form" onSubmit={submit}><div className="launch-checks">{options.map(([key, label]) => <label key={key}><input type="checkbox" name={key} defaultChecked={preference[key]} />{label}</label>)}</div>
    <Field label="Study summary"><select name="digest" defaultValue={preference.digest}><option value="off">No summary</option><option value="daily">Daily after 8 am</option><option value="weekly">Monday after 8 am</option></select></Field>
    <div className="launch-grid"><Field label="Quiet hours start" hint="Uses the time zone in your profile."><input type="time" name="quiet_start" defaultValue={preference.quiet_start?.slice(0, 5) ?? ""} /></Field><Field label="Quiet hours end"><input type="time" name="quiet_end" defaultValue={preference.quiet_end?.slice(0, 5) ?? ""} /></Field></div>
    <p className="muted">Quiet hours delay email reminders. Sign-in and recovery messages remain available so you can access your account.</p>
    {message && <p role="status">{message}</p>}{update.error && <ErrorState error={update.error} size="compact" />}<Button disabled={update.isPending}>Save preferences</Button></form>;
}

export default function NotificationSettingsPage() {
  const [page, setPage] = useState(1);
  const cache = useQueryClient();
  const preferences = useQuery({ queryKey: ["notification-preferences"], queryFn: operationsApi.preferences });
  const projects = useQuery({ queryKey: ["projects", "all"], queryFn: projectApi.listAll });
  const mutes = useQuery({ queryKey: ["project-mutes"], queryFn: operationsApi.mutes });
  const deliveries = useQuery({ queryKey: page === 1 ? ["deliveries"] : ["deliveries", page], queryFn: () => operationsApi.deliveries(page), refetchInterval: 30000 });
  const blocks = useQuery({ queryKey: ["blocks"], queryFn: operationsApi.blocks });
  const mute = useMutation({ mutationFn: ({ project, muted }: { project: string; muted: boolean }) => operationsApi.mute(project, muted), onSuccess: () => { void cache.invalidateQueries({ queryKey: ["project-mutes"] }); } });
  const unblock = useMutation({ mutationFn: (user: string) => operationsApi.block(user, false), onSuccess: () => { void cache.invalidateQueries({ queryKey: ["blocks"] }); } });
  return <div className="page-stack"><div className="page-heading"><div><h2>Notification settings</h2><p>Choose what reaches you and when.</p></div></div>
    <Panel><h3>Your preferences</h3>{preferences.isLoading ? <Loading size="compact" label="Loading notification preferences…" /> : preferences.error ? <ErrorState error={preferences.error} size="compact" retry={() => void preferences.refetch()} /> : preferences.data && <PreferenceForm preference={preferences.data} />}</Panel>
    <Panel><h3>Project notifications</h3>{projects.isLoading || mutes.isLoading ? <Loading size="compact" label="Loading project notification settings…" /> : projects.error || mutes.error ? <ErrorState error={projects.error ?? mutes.error} size="compact" retry={() => { void projects.refetch(); void mutes.refetch(); }} /> : projects.data?.results.length ? <div className="compact-list">{projects.data.results.map(project => { const muted = mutes.data?.results.some(row => row.project === project.id && row.muted) ?? false; return <div className="compact-row" key={project.id}><span>{project.name}</span><Button variant="quiet" disabled={mute.isPending} onClick={() => mute.mutate({ project: project.id, muted: !muted })}>{muted ? "Unmute" : "Mute"}</Button></div>; })}</div> : <p>No project notification settings yet.</p>}{mute.error && <p role="alert">{errorMessage(mute.error)}</p>}</Panel>
    <Panel><h3>Blocked invitations and mentions</h3><p className="muted">Blocking stops invitations and personal notifications from that person. Existing shared project records remain visible to authorised members.</p>{blocks.isLoading ? <Loading size="compact" label="Loading blocked people…" /> : blocks.error ? <ErrorState error={blocks.error} size="compact" retry={() => void blocks.refetch()} /> : blocks.data?.results.length ? blocks.data.results.map(row => <div className="compact-row" key={row.user_id}><span>{row.display_name}</span><Button variant="quiet" disabled={unblock.isPending} onClick={() => unblock.mutate(row.user_id)}>Unblock</Button></div>) : <p>No blocked people.</p>}{unblock.error && <ErrorState error={unblock.error} size="compact" />}</Panel>
    <Panel><h3>Recent email status</h3><p className="muted">Accepted means the mail server accepted the message. Confirmed delivery is shown only when the provider reports it.</p>{deliveries.isLoading ? <Loading size="compact" label="Loading email status…" /> : deliveries.error ? <ErrorState error={deliveries.error} size="compact" retry={() => void deliveries.refetch()} /> : <>{deliveries.data?.results.length ? <div className="compact-list">{deliveries.data.results.map(row => <div className="compact-row" key={row.id}><span><strong>{row.subject}</strong><small>{new Date(row.created_at).toLocaleString()}{row.failure_reason && ` · ${row.failure_reason}`}</small></span><StatusBadge value={row.status} /></div>)}</div> : <EmptyState title="No email records">Your scheduled messages will appear here.</EmptyState>}<ListPagination info={deliveries.data} page={page} onChange={setPage} label="Email status" /></>}</Panel>
  </div>;
}
