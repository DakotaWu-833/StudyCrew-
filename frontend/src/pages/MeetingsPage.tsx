import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import { accountApi, meetingApi, projectApi } from "../api/resources";
import type { Meeting, RSVP } from "../api/types";
import { formatDate, parseOptionalDateTime, toDateTimeLocal } from "../app/format";
import { Button, ConfirmAction, EmptyState, ErrorState, Field, Loading, Panel, StatusBadge } from "../components/UI";

type MeetingWrite = Pick<Meeting, "title" | "starts_at" | "ends_at" | "location" | "agenda">;

const holidaySourceLabels = {
  live: "live provider",
  cache: "current cache",
  stale: "stale cache fallback",
  unavailable: "provider unavailable",
} as const;

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
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const meetings = useQuery({ queryKey: ["meetings", projectId], queryFn: () => meetingApi.list(projectId), enabled: Boolean(projectId) });
  const me = useQuery({ queryKey: ["me"], queryFn: accountApi.me, staleTime: 60_000 });
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => projectApi.get(projectId), enabled: Boolean(projectId) });
  const refresh = () => client.invalidateQueries({ queryKey: ["meetings", projectId] });
  const fail = (value: unknown) => { setMessage(""); setError(errorMessage(value)); };
  const create = useMutation({
    mutationFn: meetingApi.create,
    onSuccess: async () => {
      await refresh();
      setShowCreate(false);
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
      setMessage("Meeting cancelled.");
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

  return <div className="page-stack">
    <div className="page-heading">
      <div><p className="eyebrow">Coordination</p><h2>Meetings</h2><p>Schedule a session, check public holidays and collect attendance.</p></div>
      {!isProjectArchived && <Button onClick={() => { setShowCreate((value) => !value); setEditingId(null); }}>{showCreate ? "Close form" : "Schedule meeting"}</Button>}
    </div>
    {(message || error) && <p className={error ? "notice notice--error" : "notice"} role={error ? "alert" : "status"}>{error || message}</p>}
    {isProjectArchived && <p className="notice" role="status">This project is archived. Meetings and RSVP evidence are read-only.</p>}
    {showCreate && !isProjectArchived && <Panel labelledBy="schedule-heading">
      <h3 id="schedule-heading">Schedule meeting</h3>
      <form className="form-grid" onSubmit={submitCreate}>
        <Field label="Meeting title"><input name="title" required minLength={3} maxLength={120} autoFocus /></Field>
        <Field label="Location or call link"><input name="location" maxLength={2048} /></Field>
        <Field label="Starts"><input name="starts_at" type="datetime-local" required /></Field>
        <Field label="Ends"><input name="ends_at" type="datetime-local" required /></Field>
        <Field label="Agenda"><textarea name="agenda" rows={4} maxLength={4000} /></Field>
        <div className="form-actions"><Button type="submit" disabled={create.isPending}>{create.isPending ? "Scheduling…" : "Schedule meeting"}</Button></div>
      </form>
    </Panel>}
    {!meetings.data?.count ? <EmptyState title="No meetings scheduled">Set a time and agenda for the next group check-in.</EmptyState> : <div className="meeting-list">
      {meetings.data.results.map((meeting) => {
        const canManage = !isProjectArchived && (meeting.organiser.id === me.data?.user.id || ["owner", "facilitator"].includes(project.data?.current_user_role ?? ""));
        const isEditing = editingId === meeting.id;
        return <Panel key={meeting.id} className={meeting.cancelled_at ? "meeting meeting--cancelled" : "meeting"}>
          <div className="meeting__heading">
            <div>
              <div className="heading-badges"><StatusBadge value={meeting.cancelled_at ? "cancelled" : "scheduled"} /><span>Organised by {meeting.organiser.display_name}</span></div>
              <h3>{meeting.title}</h3>
              <p>{formatDate(meeting.starts_at)} – {formatDate(meeting.ends_at)}</p>
            </div>
            <span className="row-actions">
              <Button variant="quiet" onClick={() => holiday.mutate(meeting.id)} disabled={holiday.isPending}>Check public holiday</Button>
              {canManage && !meeting.cancelled_at && <Button variant="secondary" onClick={() => { setEditingId(isEditing ? null : meeting.id); setShowCreate(false); }}>{isEditing ? "Close edit" : "Edit meeting"}</Button>}
            </span>
          </div>
          {isEditing ? <form className="form-grid meeting__edit" onSubmit={(event) => submitEdit(meeting.id, event)}>
            <Field label="Meeting title"><input name="title" required minLength={3} maxLength={120} defaultValue={meeting.title} autoFocus /></Field>
            <Field label="Location or call link"><input name="location" maxLength={2048} defaultValue={meeting.location} /></Field>
            <Field label="Starts"><input name="starts_at" type="datetime-local" required defaultValue={toDateTimeLocal(meeting.starts_at)} /></Field>
            <Field label="Ends"><input name="ends_at" type="datetime-local" required defaultValue={toDateTimeLocal(meeting.ends_at)} /></Field>
            <Field label="Agenda"><textarea name="agenda" rows={4} maxLength={4000} defaultValue={meeting.agenda} /></Field>
            <div className="form-actions"><Button type="submit" disabled={update.isPending}>{update.isPending ? "Saving…" : "Save meeting"}</Button><Button type="button" variant="quiet" onClick={() => setEditingId(null)}>Cancel edit</Button></div>
          </form> : <div className="meeting__details"><p><strong>Location:</strong> {meeting.location || "To be confirmed"}</p><p>{meeting.agenda || "No agenda supplied."}</p></div>}
          <div className="meeting__footer">
            <div className="attendance" aria-label="Attendance summary"><span>✓ {meeting.attendance_counts.accepted}</span><span>– {meeting.attendance_counts.pending}</span><span>× {meeting.attendance_counts.declined}</span></div>
            {!meeting.cancelled_at && !isProjectArchived && <form className="rsvp-form" onSubmit={(event) => submitRsvp(meeting.id, event)}>
              <label className="field field--compact"><span className="field__label">Your RSVP</span><select name="response" defaultValue={meeting.my_response}><option value="pending">Pending</option><option value="accepted">Attending</option><option value="declined">Not attending</option></select></label>
              <label className="field field--compact rsvp-form__note"><span className="field__label">Availability note</span><input name="availability_note" maxLength={500} defaultValue={meeting.my_availability_note} placeholder="Optional note" /></label>
              <Button type="submit" variant="secondary" disabled={rsvp.isPending}>{rsvp.isPending ? "Saving…" : "Save RSVP"}</Button>
              {canManage && <ConfirmAction triggerLabel="Cancel meeting" confirmLabel="Cancel meeting" message={`Cancel ${meeting.title}? Attendance history will be retained.`} busy={cancel.isPending} onConfirm={() => cancel.mutate(meeting.id)} />}
            </form>}
          </div>
        </Panel>;
      })}
    </div>}
  </div>;
}
