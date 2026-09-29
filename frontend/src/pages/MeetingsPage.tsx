import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import { accountApi, meetingApi, projectApi } from "../api/resources";
import type { Meeting, RSVP } from "../api/types";
import { formatDate, meetingDateTimeLimit, parseOptionalDateTime, toDateTimeLocal } from "../app/format";
import { Button, ConfirmAction, EmptyState, ErrorState, Field, Loading, Panel, StatusBadge } from "../components/UI";

type MeetingWrite = Pick<Meeting, "title" | "starts_at" | "ends_at" | "location" | "agenda">;
type MeetingScope = "active" | "archived" | "all";

const holidaySourceLabels = {
  live: "live provider",
  cache: "current cache",
  stale: "stale cache fallback",
  unavailable: "provider unavailable",
} as const;

const emptyStates: Record<MeetingScope, { title: string; detail: string }> = {
  active: { title: "No current meetings", detail: "Schedule a session for the next group check-in." },
  archived: { title: "No archived meetings", detail: "Cancelled and ended meetings can be archived as read-only evidence." },
  all: { title: "No meetings recorded", detail: "Schedule a session for the next group check-in." },
};

function meetingFields(form: HTMLFormElement): MeetingWrite | null {
  const data = new FormData(form);
  const starts = parseOptionalDateTime(String(data.get("starts_at")));
  const ends = parseOptionalDateTime(String(data.get("ends_at")));
  if (!starts || !ends) return null;
  return {
    title: String(data.get("title")),
    starts_at: starts,
    ends_at: ends,
    location: String(data.get("location")),
    agenda: String(data.get("agenda")),
  };
}

export default function MeetingsPage() {
  const { projectId = "" } = useParams();
  const client = useQueryClient();
  const [scope, setScope] = useState<MeetingScope>("active");
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [nowMs, setNowMs] = useState(() => Date.now());
  const maximumMeetingTime = meetingDateTimeLimit();
  const meetings = useQuery({
    queryKey: ["meetings", projectId, scope],
    queryFn: () => meetingApi.list(projectId, scope),
    enabled: Boolean(projectId),
  });
  const me = useQuery({ queryKey: ["me"], queryFn: accountApi.me, staleTime: 60_000 });
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => projectApi.get(projectId), enabled: Boolean(projectId) });
  useEffect(() => {
    const nextEnd = Math.min(
      ...(meetings.data?.results
        .filter((meeting) => meeting.lifecycle_state === "scheduled")
        .map((meeting) => Date.parse(meeting.ends_at))
        .filter((endsAt) => endsAt > nowMs) ?? []),
    );
    if (!Number.isFinite(nextEnd)) return;
    const delay = Math.min(2_147_483_647, Math.max(0, nextEnd - Date.now() + 100));
    const timer = window.setTimeout(() => setNowMs(Date.now()), delay);
    return () => window.clearTimeout(timer);
  }, [meetings.data?.results, nowMs]);
  const refresh = () => client.invalidateQueries({ queryKey: ["meetings", projectId] });
  const fail = (value: unknown) => { setMessage(""); setError(errorMessage(value)); };
  const create = useMutation({
    mutationFn: meetingApi.create,
    onSuccess: async () => {
      await refresh();
      setShowCreate(false);
      setScope("active");
      setError("");
      setMessage("Meeting scheduled.");
    },
    onError: fail,
  });
  const update = useMutation({
    mutationFn: ({ id, data }: { id: string; data: MeetingWrite }) => meetingApi.update(id, data),
    onSuccess: async () => {
      await refresh();
      setEditingId(null);
      setError("");
      setMessage("Meeting details saved.");
    },
    onError: fail,
  });
  const rsvp = useMutation({
    mutationFn: ({ id, response, note }: { id: string; response: RSVP; note: string }) => meetingApi.rsvp(id, response, note),
    onSuccess: async () => {
      await refresh();
      setError("");
      setMessage("RSVP and availability note updated.");
    },
    onError: fail,
  });
  const cancel = useMutation({
    mutationFn: meetingApi.cancel,
    onSuccess: async () => {
      await refresh();
      setEditingId(null);
      setError("");
      setMessage("Meeting cancelled. It can now be archived when the team no longer needs it in the current list.");
    },
    onError: fail,
  });
  const archive = useMutation({
    mutationFn: meetingApi.archive,
    onSuccess: async () => {
      await refresh();
      setEditingId(null);
      setError("");
      setMessage("Meeting archived as read-only evidence.");
    },
    onError: fail,
  });
  const reminder = useMutation({
    mutationFn: meetingApi.sendReminder,
    onSuccess: (delivery) => {
      setError("");
      setMessage(`Email reminder sent to ${delivery.recipient_count} project member${delivery.recipient_count === 1 ? "" : "s"}.`);
    },
    onError: fail,
  });
  const holiday = useMutation({
    mutationFn: meetingApi.holiday,
    onSuccess: (advice) => {
      setError("");
      setMessage(`${advice.message} Source: ${holidaySourceLabels[advice.source]}.`);
    },
    onError: fail,
  });

  const submitCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setMessage("");
    const values = meetingFields(event.currentTarget);
    if (!values) { setError("Choose a valid start and end time."); return; }
    create.mutate({ project: projectId, ...values });
  };

  const submitEdit = (meetingId: string, event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setMessage("");
    const values = meetingFields(event.currentTarget);
    if (!values) { setError("Choose a valid start and end time."); return; }
    update.mutate({ id: meetingId, data: values });
  };

  const submitRsvp = (meetingId: string, event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setMessage("");
    const data = new FormData(event.currentTarget);
    rsvp.mutate({
      id: meetingId,
      response: String(data.get("response")) as RSVP,
      note: String(data.get("availability_note")),
    });
  };

  if (meetings.isLoading || me.isLoading || project.isLoading) return <Loading label="Loading meetings…" />;
  if (meetings.error || me.error || project.error) {
    return <ErrorState error={meetings.error ?? me.error ?? project.error} retry={() => { void meetings.refetch(); void me.refetch(); void project.refetch(); }} />;
  }
  const isProjectArchived = Boolean(project.data?.archived_at);
  const currentRole = project.data?.current_user_role ?? "";
  const isProjectManager = ["owner", "facilitator"].includes(currentRole);

  return <div className="page-stack">
    <div className="page-heading">
      <div><p className="eyebrow">Coordination</p><h2>Meetings</h2><p>Schedule sessions, collect attendance and retain completed records as evidence.</p></div>
      {!isProjectArchived && <Button onClick={() => { setShowCreate((value) => !value); setEditingId(null); }}>{showCreate ? "Close form" : "Schedule meeting"}</Button>}
    </div>
    {(message || error) && <p className={error ? "notice notice--error" : "notice"} role={error ? "alert" : "status"}>{error || message}</p>}
    {isProjectArchived && <p className="notice" role="status">This project is archived. Meeting and RSVP evidence are read-only.</p>}
    <Panel labelledBy="meeting-records-heading">
      <div className="section-heading"><div><h3 id="meeting-records-heading">Meeting records</h3><p className="muted">Archived meetings remain available without cluttering current coordination.</p></div></div>
      <div className="meeting-scope" role="group" aria-label="Meeting record scope">
        {(["active", "archived", "all"] as const).map((value) => <Button key={value} variant={scope === value ? "secondary" : "quiet"} onClick={() => { setScope(value); setEditingId(null); setShowCreate(false); }} aria-pressed={scope === value}>{value === "active" ? "Current" : value === "archived" ? "Archived" : "All records"}</Button>)}
      </div>
    </Panel>
    {showCreate && !isProjectArchived && <Panel labelledBy="schedule-heading">
      <h3 id="schedule-heading">Schedule meeting</h3>
      <form className="form-grid" onSubmit={submitCreate}>
        <Field label="Meeting title"><input name="title" required minLength={3} maxLength={120} autoFocus /></Field>
        <Field label="Location or call link"><input name="location" maxLength={2048} /></Field>
        <Field label="Starts" hint="Meetings can be scheduled up to ten years ahead."><input name="starts_at" type="datetime-local" required max={maximumMeetingTime} /></Field>
        <Field label="Ends"><input name="ends_at" type="datetime-local" required max={maximumMeetingTime} /></Field>
        <Field label="Agenda"><textarea name="agenda" rows={4} maxLength={4000} /></Field>
        <div className="form-actions"><Button type="submit" disabled={create.isPending}>{create.isPending ? "Scheduling…" : "Schedule meeting"}</Button></div>
      </form>
    </Panel>}
    {!meetings.data?.count ? <EmptyState title={emptyStates[scope].title}>{emptyStates[scope].detail}</EmptyState> : <div className="meeting-list">
      {meetings.data.results.map((meeting) => {
        const canManage = !isProjectArchived && !meeting.archived_at && (meeting.organiser.id === me.data?.user.id || isProjectManager);
        const lifecycleState = meeting.lifecycle_state === "scheduled" && Date.parse(meeting.ends_at) <= nowMs ? "ended" : meeting.lifecycle_state;
        const canSendReminder = !isProjectArchived && isProjectManager && (project.data?.member_count ?? 0) > 1 && lifecycleState === "scheduled";
        const canArchive = canManage && ["cancelled", "ended"].includes(lifecycleState);
        const isEditing = editingId === meeting.id;
        const isScheduled = lifecycleState === "scheduled";
        return <Panel key={meeting.id} className={["meeting", meeting.cancelled_at ? "meeting--cancelled" : "", meeting.archived_at ? "meeting--archived" : ""].filter(Boolean).join(" ")}>
          <div className="meeting__heading">
            <div>
              <div className="heading-badges"><StatusBadge value={lifecycleState} /><span>Organised by {meeting.organiser.display_name}</span></div>
              <h3>{meeting.title}</h3>
              <p>{formatDate(meeting.starts_at)} – {formatDate(meeting.ends_at)}</p>
            </div>
            <span className="row-actions">
              <Button variant="quiet" onClick={() => holiday.mutate(meeting.id)} disabled={holiday.isPending}>Check public holiday</Button>
              {canManage && isScheduled && <Button variant="secondary" onClick={() => { setEditingId(isEditing ? null : meeting.id); setShowCreate(false); }}>{isEditing ? "Close edit" : "Edit meeting"}</Button>}
            </span>
          </div>
          {meeting.archived_at && <p className="meeting__read-only" role="note">Archived {formatDate(meeting.archived_at)} · retained as read-only meeting and RSVP evidence.</p>}
          {isEditing ? <form className="form-grid meeting__edit" onSubmit={(event) => submitEdit(meeting.id, event)}>
            <Field label="Meeting title"><input name="title" required minLength={3} maxLength={120} defaultValue={meeting.title} autoFocus /></Field>
            <Field label="Location or call link"><input name="location" maxLength={2048} defaultValue={meeting.location} /></Field>
            <Field label="Starts" hint="Meetings can be scheduled up to ten years ahead."><input name="starts_at" type="datetime-local" required max={maximumMeetingTime} defaultValue={toDateTimeLocal(meeting.starts_at)} /></Field>
            <Field label="Ends"><input name="ends_at" type="datetime-local" required max={maximumMeetingTime} defaultValue={toDateTimeLocal(meeting.ends_at)} /></Field>
            <Field label="Agenda"><textarea name="agenda" rows={4} maxLength={4000} defaultValue={meeting.agenda} /></Field>
            <div className="form-actions"><Button type="submit" disabled={update.isPending}>{update.isPending ? "Saving…" : "Save meeting"}</Button><Button type="button" variant="quiet" onClick={() => setEditingId(null)}>Cancel edit</Button></div>
          </form> : <div className="meeting__details"><p><strong>Location:</strong> {meeting.location || "To be confirmed"}</p><p>{meeting.agenda || "No agenda supplied."}</p></div>}
          {isScheduled && !isProjectArchived && <form className="rsvp-form" onSubmit={(event) => submitRsvp(meeting.id, event)}>
            <label className="field field--compact"><span className="field__label">Your RSVP</span><select name="response" defaultValue={meeting.my_response}><option value="pending">Pending</option><option value="accepted">Attending</option><option value="declined">Not attending</option></select></label>
            <label className="field field--compact rsvp-form__note"><span className="field__label">Availability note</span><input name="availability_note" maxLength={500} defaultValue={meeting.my_availability_note} placeholder="Optional note" /></label>
            <Button type="submit" variant="secondary" disabled={rsvp.isPending}>{rsvp.isPending ? "Saving…" : "Save RSVP"}</Button>
          </form>}
          <div className="meeting__footer">
            <div className="attendance" aria-label="Attendance summary"><span>✓ {meeting.attendance_counts.accepted} accepted</span><span>– {meeting.attendance_counts.pending} pending</span><span>× {meeting.attendance_counts.declined} declined</span></div>
            <div className="row-actions">
              {canSendReminder && <ConfirmAction triggerLabel="Email reminder" triggerVariant="quiet" confirmLabel="Send reminder" message="Send one reminder email to each current project member except yourself?" busy={reminder.isPending} onConfirm={() => reminder.mutate(meeting.id)} />}
              {canManage && isScheduled && <ConfirmAction triggerLabel="Cancel meeting" confirmLabel="Cancel meeting" message={`Cancel ${meeting.title}? Attendance history will be retained and the meeting can then be archived.`} busy={cancel.isPending} onConfirm={() => cancel.mutate(meeting.id)} />}
              {canArchive && <ConfirmAction triggerLabel="Archive meeting" confirmLabel="Archive meeting" message={`Archive ${meeting.title}? It will move out of Current and remain available as read-only evidence.`} busy={archive.isPending} onConfirm={() => archive.mutate(meeting.id)} />}
            </div>
          </div>
        </Panel>;
      })}
    </div>}
  </div>;
}
