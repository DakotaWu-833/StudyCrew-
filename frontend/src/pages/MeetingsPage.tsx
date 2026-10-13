import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { APIError, errorMessage, fieldErrors } from "../api/client";
import { accountApi, meetingApi, projectApi } from "../api/resources";
import type { Meeting, RSVP } from "../api/types";
import { earliestMeetingDateTime, formatDate, meetingDateTimeLimit, parseOptionalDateTime, toDateTimeLocal } from "../app/format";
import { Button, ConfirmAction, EmptyState, ErrorState, Field, FloatingPanel, Loading, Panel, StatusBadge } from "../components/UI";

type MeetingWrite = Pick<Meeting, "title" | "starts_at" | "ends_at" | "location" | "agenda">;
type MeetingScope = "active" | "archived" | "all";
type MeetingStateFilter = "all" | Meeting["lifecycle_state"];

function meetingLifecycle(meeting: Meeting, nowMs: number): Meeting["lifecycle_state"] {
  if (meeting.archived_at) return "archived";
  if (meeting.cancelled_at) return "cancelled";
  const endsAt = Date.parse(meeting.ends_at);
  if (!Number.isFinite(endsAt)) return meeting.lifecycle_state;
  return endsAt <= nowMs ? "ended" : "scheduled";
}

function meetingDateRange(meeting: Meeting): string {
  const start = Date.parse(meeting.starts_at);
  const end = Date.parse(meeting.ends_at);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return "Meeting date unavailable";
  return `${formatDate(meeting.starts_at)} – ${formatDate(meeting.ends_at)}`;
}

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

function meetingFields(form: HTMLFormElement, earliest: string, latest: string): MeetingWrite | null {
  const data = new FormData(form);
  const startsValue = String(data.get("starts_at"));
  const endsValue = String(data.get("ends_at"));
  const starts = parseOptionalDateTime(startsValue);
  const ends = parseOptionalDateTime(endsValue);
  const earliestInstant = parseOptionalDateTime(earliest);
  const latestInstant = parseOptionalDateTime(latest);
  if (!starts || !ends || !earliestInstant || !latestInstant) return null;
  if (
    Date.parse(starts) < Date.parse(earliestInstant)
    || Date.parse(ends) < Date.parse(earliestInstant)
    || Date.parse(starts) > Date.parse(latestInstant)
    || Date.parse(ends) > Date.parse(latestInstant)
    || Date.parse(ends) <= Date.parse(starts)
  ) return null;
  return {
    title: String(data.get("title")),
    starts_at: starts,
    ends_at: ends,
    location: String(data.get("location")),
    agenda: String(data.get("agenda")),
  };
}

function formHasChanges(form: HTMLFormElement): boolean {
  return Array.from(form.elements).some((control) =>
    (control instanceof HTMLInputElement || control instanceof HTMLTextAreaElement)
    && control.value !== control.defaultValue,
  );
}

export default function MeetingsPage() {
  const { projectId = "" } = useParams();
  const client = useQueryClient();
  const [scope, setScope] = useState<MeetingScope>("active");
  const [stateFilter, setStateFilter] = useState<MeetingStateFilter>("all");
  const [search, setSearch] = useState("");
  const [settledSearch, setSettledSearch] = useState("");
  const [page, setPage] = useState(1);
  const [showCreate, setShowCreate] = useState(false);
  const [createDirty, setCreateDirty] = useState(false);
  const [editDirty, setEditDirty] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [nowMs, setNowMs] = useState(() => Date.now());
  const earliestMeetingTime = earliestMeetingDateTime();
  const maximumMeetingTime = meetingDateTimeLimit();
  const dateRangeHint = `Choose a date from ${earliestMeetingTime.slice(0, 10)} through ${maximumMeetingTime.slice(0, 10)}.`;
  const meetings = useQuery({
    queryKey: ["meetings", projectId, scope, stateFilter, settledSearch, page],
    queryFn: () => meetingApi.listPage(projectId, { scope, state: stateFilter, search: settledSearch, page }),
    enabled: Boolean(projectId),
    placeholderData: (previousData, previousQuery) => previousQuery?.queryKey[1] === projectId ? previousData : undefined,
  });
  const me = useQuery({ queryKey: ["me"], queryFn: accountApi.me, staleTime: 60_000 });
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => projectApi.get(projectId), enabled: Boolean(projectId) });
  const matchingCount = meetings.data?.count ?? 0;
  const pageCount = Math.max(1, Math.ceil(matchingCount / 5));
  const visibleMeetings = meetings.data?.results ?? [];
  const isUpdating = meetings.isFetching || search.trim() !== settledSearch;
  useEffect(() => {
    const timer = window.setTimeout(() => setSettledSearch(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);
  useEffect(() => {
    setScope("active"); setStateFilter("all"); setSearch(""); setSettledSearch(""); setPage(1);
    setEditingId(null); setShowCreate(false); setError(""); setMessage("");
  }, [projectId]);
  useEffect(() => {
    // A deleted/archived last record can invalidate its page; recover without
    // leaving the user on an error-only screen. Project errors remain visible.
    if (page > 1 && meetings.error instanceof APIError && meetings.error.status === 404) setPage(1);
  }, [meetings.error, page]);
  useEffect(() => {
    const nextEnd = Math.min(
      ...(meetings.data?.results
        .filter((meeting) => meeting.lifecycle_state === "scheduled")
        .map((meeting) => Date.parse(meeting.ends_at))
        .filter((endsAt) => endsAt > nowMs) ?? []),
    );
    if (!Number.isFinite(nextEnd)) return;
    const delay = Math.min(2_147_483_647, Math.max(0, nextEnd - Date.now() + 100));
    const timer = window.setTimeout(() => {
      setNowMs(Date.now());
      void client.invalidateQueries({ queryKey: ["meetings", projectId] });
    }, delay);
    return () => window.clearTimeout(timer);
  }, [client, meetings.data?.results, nowMs, projectId]);
  const refresh = () => client.invalidateQueries({ queryKey: ["meetings", projectId] });
  const fail = (value: unknown) => { setMessage(""); setError(errorMessage(value)); };
  const create = useMutation({
    mutationFn: meetingApi.create,
    onSuccess: async () => {
      await refresh();
      setShowCreate(false);
      setScope("active");
      setStateFilter("all");
      setSearch("");
      setSettledSearch("");
      setPage(1);
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
  const restore = useMutation({
    mutationFn: meetingApi.restore,
    onSuccess: async () => {
      await refresh();
      setEditingId(null);
      setScope("active");
      setStateFilter("all");
      setSearch("");
      setSettledSearch("");
      setPage(1);
      setError("");
      setMessage("Meeting restored to current records.");
    },
    onError: fail,
  });
  const reminder = useMutation({
    mutationFn: meetingApi.sendReminder,
    onSuccess: (delivery) => {
      setError("");
      setMessage(`Email reminder ${delivery.delivery_status === "queued" ? "queued for" : "sent to"} ${delivery.recipient_count} project member${delivery.recipient_count === 1 ? "" : "s"}.`);
    },
    onError: fail,
  });
  const holiday = useMutation({
    mutationFn: meetingApi.holiday,
  });
  const createErrors = error ? fieldErrors(create.error) : {};
  const editErrors = error ? fieldErrors(update.error) : {};

  const submitCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setMessage("");
    const values = meetingFields(event.currentTarget, earliestMeetingTime, maximumMeetingTime);
    if (!values) { setError(`Choose dates from today through ${maximumMeetingTime.slice(0, 10)} and make the end later than the start.`); return; }
    create.mutate({ project: projectId, ...values });
  };

  const submitEdit = (meetingId: string, event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setMessage("");
    const values = meetingFields(event.currentTarget, earliestMeetingTime, maximumMeetingTime);
    if (!values) { setError(`Choose dates from today through ${maximumMeetingTime.slice(0, 10)} and make the end later than the start.`); return; }
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

  if (me.isLoading || project.isLoading) return <Loading label="Loading meetings…" />;
  if (me.error || project.error) {
    return <ErrorState error={me.error ?? project.error} retry={() => { void me.refetch(); void project.refetch(); }} />;
  }
  const isProjectArchived = Boolean(project.data?.archived_at);
  const currentRole = project.data?.current_user_role ?? "";
  const isProjectManager = ["owner", "facilitator"].includes(currentRole);

  return <div className="page-stack">
    <div className="page-heading">
      <div><p className="eyebrow">Coordination</p><h2>Meetings</h2><p>Schedule sessions, collect attendance and retain completed records as evidence.</p></div>
      {!isProjectArchived && <Button type="button" aria-expanded={showCreate} onClick={() => { setError(""); setCreateDirty(false); create.reset(); setShowCreate(true); setEditingId(null); }}>Schedule meeting</Button>}
    </div>
    {(message || error) && <p className={error ? "notice notice--error" : "notice"} role={error ? "alert" : "status"}>{error || message}</p>}
    {isProjectArchived && <p className="notice" role="status">This project is archived. Meeting and RSVP evidence are read-only.</p>}
    <Panel labelledBy="meeting-records-heading">
      <div className="section-heading"><div><h3 id="meeting-records-heading">Meeting records</h3><p className="muted">Archived meetings remain available without cluttering current coordination.</p></div></div>
      <div className="meeting-scope" role="group" aria-label="Meeting record scope">
        {(["active", "archived", "all"] as const).map((value) => <Button key={value} variant={scope === value ? "secondary" : "quiet"} onClick={() => { setScope(value); setPage(1); setEditingId(null); setShowCreate(false); }} aria-pressed={scope === value}>{value === "active" ? "Current" : value === "archived" ? "Archived" : "All records"}</Button>)}
      </div>
      <div className="meeting-filters">
        <Field label="Search meetings"><input type="search" maxLength={120} value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="Title, agenda, location, organiser" /></Field>
        <Field label="Meeting status"><select value={stateFilter} onChange={(event) => { setStateFilter(event.target.value as MeetingStateFilter); setPage(1); }}>
          <option value="all">All statuses</option><option value="scheduled">Scheduled</option><option value="ended">Ended</option><option value="cancelled">Cancelled</option><option value="archived">Archived</option>
        </select></Field>
        {(search || stateFilter !== "all") && <Button type="button" variant="quiet" onClick={() => { setSearch(""); setSettledSearch(""); setStateFilter("all"); setPage(1); }}>Clear filters</Button>}
        <p className="meeting-filters__count" aria-live="polite">{isUpdating ? "Updating meetings…" : `${matchingCount} matching meeting${matchingCount === 1 ? "" : "s"}`}</p>
      </div>
    </Panel>
    {showCreate && !isProjectArchived && <FloatingPanel title="Schedule meeting" onDismiss={() => setShowCreate(false)} busy={create.isPending} dirty={createDirty}>
      <form className="form-grid" onSubmit={submitCreate} onChange={(event) => setCreateDirty(formHasChanges(event.currentTarget))}>
        <Field label="Meeting title" error={createErrors.title}><input name="title" required minLength={3} maxLength={120} autoFocus /></Field>
        <Field label="Location or call link" error={createErrors.location}><input name="location" maxLength={2048} /></Field>
        <Field label="Starts" hint={dateRangeHint} error={createErrors.starts_at}><input name="starts_at" type="datetime-local" required min={earliestMeetingTime} max={maximumMeetingTime} /></Field>
        <Field label="Ends" hint={dateRangeHint} error={createErrors.ends_at}><input name="ends_at" type="datetime-local" required min={earliestMeetingTime} max={maximumMeetingTime} /></Field>
        <Field label="Agenda" error={createErrors.agenda}><textarea name="agenda" rows={4} maxLength={4000} /></Field>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="form-actions"><Button type="submit" disabled={create.isPending}>{create.isPending ? "Scheduling…" : "Schedule meeting"}</Button></div>
      </form>
    </FloatingPanel>}
    {meetings.isPending ? <Loading label="Loading meeting records…" /> : meetings.error ? <ErrorState error={meetings.error} retry={() => { void meetings.refetch(); }} /> : !visibleMeetings.length ? <EmptyState title={settledSearch || stateFilter !== "all" ? "No matching meetings" : emptyStates[scope].title}>{settledSearch || stateFilter !== "all" ? "Try another search or clear the filters." : emptyStates[scope].detail}</EmptyState> : <>
    <div className="meeting-list" aria-busy={isUpdating}>
      {visibleMeetings.map((meeting) => {
        const canManage = !isProjectArchived && !meeting.archived_at && (meeting.organiser.id === me.data?.user.id || isProjectManager);
        const canRestore = !isProjectArchived && Boolean(meeting.archived_at) && (meeting.organiser.id === me.data?.user.id || isProjectManager);
        const lifecycleState = meetingLifecycle(meeting, nowMs);
        const canSendReminder = !isProjectArchived && isProjectManager && (project.data?.member_count ?? 0) > 1 && lifecycleState === "scheduled";
        const canArchive = canManage && ["cancelled", "ended"].includes(lifecycleState);
        const isEditing = editingId === meeting.id;
        const isScheduled = lifecycleState === "scheduled";
        const canEditDates = toDateTimeLocal(meeting.starts_at) >= earliestMeetingTime;
        const holidayResultClass = holiday.data?.available && holiday.data.is_public_holiday === true
          ? "meeting__holiday-result--holiday"
          : holiday.data?.available && holiday.data.is_public_holiday === false
            ? "meeting__holiday-result--available"
            : "meeting__holiday-result--unknown";
        return <Panel key={meeting.id} className={["meeting", meeting.cancelled_at ? "meeting--cancelled" : "", meeting.archived_at ? "meeting--archived" : ""].filter(Boolean).join(" ")}>
          <div className="meeting__heading">
            <div>
              <div className="heading-badges"><StatusBadge value={lifecycleState} /><span>Organised by {meeting.organiser.display_name}</span></div>
              <h3>{meeting.title}</h3>
              <p>{meetingDateRange(meeting)}</p>
            </div>
            <div className="meeting__heading-actions">
              <div className="meeting__holiday-check">
                <Button type="button" variant="quiet" onClick={() => holiday.mutate(meeting.id)} disabled={holiday.isPending}>{holiday.isPending && holiday.variables === meeting.id ? "Checking…" : "Check public holiday"}</Button>
                {holiday.variables === meeting.id && holiday.isPending && <small className="meeting__holiday-result" role="status">Checking public-holiday information…</small>}
                {holiday.variables === meeting.id && !holiday.isPending && holiday.data && <small className={`meeting__holiday-result ${holidayResultClass}`} role="status">{holiday.data.message} Source: {holidaySourceLabels[holiday.data.source]}.</small>}
                {holiday.variables === meeting.id && !holiday.isPending && holiday.error && <small className="meeting__holiday-result meeting__holiday-result--error" role="alert">{errorMessage(holiday.error)}</small>}
              </div>
              {canManage && isScheduled && canEditDates && <Button variant="secondary" onClick={() => { setError(""); setEditDirty(false); update.reset(); setEditingId(isEditing ? null : meeting.id); setShowCreate(false); }}>{isEditing ? "Close edit" : "Edit meeting"}</Button>}
            </div>
          </div>
          {meeting.archived_at && <p className="meeting__read-only" role="note">Archived {formatDate(meeting.archived_at)} · retained as read-only meeting and RSVP evidence.</p>}
          <div className="meeting__details"><p><strong>Location:</strong> {meeting.location || "To be confirmed"}</p><p>{meeting.agenda || "No agenda supplied."}</p></div>
          {isEditing && <FloatingPanel title="Edit meeting" onDismiss={() => setEditingId(null)} busy={update.isPending} dirty={editDirty}>
            <form className="form-grid" onSubmit={(event) => submitEdit(meeting.id, event)} onChange={(event) => setEditDirty(formHasChanges(event.currentTarget))}>
            <Field label="Meeting title" error={editErrors.title}><input name="title" required minLength={3} maxLength={120} defaultValue={meeting.title} autoFocus /></Field>
            <Field label="Location or call link" error={editErrors.location}><input name="location" maxLength={2048} defaultValue={meeting.location} /></Field>
            <Field label="Starts" hint={dateRangeHint} error={editErrors.starts_at}><input name="starts_at" type="datetime-local" required min={earliestMeetingTime} max={maximumMeetingTime} defaultValue={toDateTimeLocal(meeting.starts_at)} /></Field>
            <Field label="Ends" hint={dateRangeHint} error={editErrors.ends_at}><input name="ends_at" type="datetime-local" required min={earliestMeetingTime} max={maximumMeetingTime} defaultValue={toDateTimeLocal(meeting.ends_at)} /></Field>
            <Field label="Agenda" error={editErrors.agenda}><textarea name="agenda" rows={4} maxLength={4000} defaultValue={meeting.agenda} /></Field>
            {error && <p className="form-error" role="alert">{error}</p>}
            <div className="form-actions"><Button type="submit" disabled={update.isPending}>{update.isPending ? "Saving…" : "Save meeting"}</Button></div>
            </form>
          </FloatingPanel>}
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
              {canRestore && <ConfirmAction triggerLabel="Restore to current" triggerVariant="secondary" confirmLabel="Restore meeting" message={`Restore ${meeting.title} to Current? Its cancelled or ended state and attendance evidence will be preserved.`} busy={restore.isPending} onConfirm={() => restore.mutate(meeting.id)} />}
            </div>
          </div>
        </Panel>;
      })}
    </div>
    {matchingCount > 5 && <nav className="meeting-pagination" aria-label="Meeting record pages">
      <Button type="button" variant="secondary" disabled={page <= 1 || isUpdating} onClick={() => setPage((current) => Math.max(1, current - 1))}>Previous</Button>
      <p aria-live="polite">{meetings.isPlaceholderData ? "Updating page…" : `Showing ${(page - 1) * 5 + 1}–${Math.min(page * 5, matchingCount)} of ${matchingCount} · Page ${page} of ${pageCount}`}</p>
      <Button type="button" variant="secondary" disabled={page >= pageCount || isUpdating} onClick={() => setPage((current) => Math.min(pageCount, current + 1))}>Next</Button>
    </nav>}
    </>}
  </div>;
}
