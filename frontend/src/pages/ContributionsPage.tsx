import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import { exportApi, projectApi } from "../api/resources";
import { formatDate, titleCase, today } from "../app/format";
import ContributionDashboard from "../components/ContributionDashboard";
import { Button, EmptyState, ErrorState, Field, Loading, Panel, StatusBadge } from "../components/UI";

const eventTypes = [
  "",
  "project_created",
  "project_updated",
  "project_archived",
  "invitation_created",
  "invitation_declined",
  "invitation_cancelled",
  "invitation_expired",
  "member_joined",
  "member_role_changed",
  "member_removed",
  "ownership_transferred",
  "task_created",
  "task_updated",
  "task_archived",
  "task_assignees_changed",
  "task_assigned",
  "task_unassigned",
  "task_status_changed",
  "comment_created",
  "comment_edited",
  "comment_deleted",
  "comment_moderated",
  "comment_reported",
  "meeting_created",
  "meeting_updated",
  "meeting_cancelled",
  "meeting_archived",
  "meeting_rsvp",
  "task_reminder_sent",
  "meeting_reminder_sent",
  "export_requested",
  "export_ready",
  "export_failed",
];

export default function ContributionsPage() {
  const { projectId = "" } = useParams();
  const client = useQueryClient();
  const [range, setRange] = useState({ range_start: today(-30), range_end: today(), event_type: "" });
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const insights = useQuery({ queryKey: ["insights", projectId, range], queryFn: () => projectApi.insights(projectId, range), enabled: Boolean(projectId) });
  const exports = useQuery({ queryKey: ["exports"], queryFn: exportApi.list });
  const createExport = useMutation({
    mutationFn: (request: { format: "csv" | "pdf"; range_start: string; range_end: string }) => exportApi.create({ project: projectId, ...request }),
    onSuccess: async (job) => {
      await client.invalidateQueries({ queryKey: ["exports"] });
      if (job.status === "ready") {
        setError("");
        setMessage("Evidence export is ready to download.");
      } else {
        setMessage("");
        setError(`${job.error_message || "Export generation failed."} Use Export CSV or Export PDF to retry.`);
      }
    },
    onError: (value) => { setMessage(""); setError(errorMessage(value)); },
  });
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    setRange({ range_start: String(data.get("range_start")), range_end: String(data.get("range_end")), event_type: String(data.get("event_type")) });
  };
  const relevantExports = exports.data?.results.filter((job) => job.project === projectId) ?? [];

  return <div className="page-stack">
    <div className="page-heading"><div><p className="eyebrow">Factual evidence</p><h2>Contributions</h2><p>Review recorded work by date and activity type. Counts describe actions; they do not rank people.</p></div><span className="row-actions"><Button variant="secondary" onClick={() => createExport.mutate({ format: "csv", range_start: range.range_start, range_end: range.range_end })} disabled={createExport.isPending}>Export CSV</Button><Button onClick={() => createExport.mutate({ format: "pdf", range_start: range.range_start, range_end: range.range_end })} disabled={createExport.isPending}>Export PDF</Button></span></div>
    {(message || error) && <p className={error ? "notice notice--error" : "notice"} role={error ? "alert" : "status"}>{error || message}</p>}
    <Panel labelledBy="evidence-filter-heading"><h3 id="evidence-filter-heading" className="sr-only">Evidence filters</h3><form className="filter-bar" onSubmit={submit}>
      <Field label="From"><input type="date" name="range_start" defaultValue={range.range_start} required /></Field>
      <Field label="To"><input type="date" name="range_end" defaultValue={range.range_end} required /></Field>
      <Field label="Activity type"><select name="event_type" defaultValue={range.event_type}>{eventTypes.map((value) => <option key={value || "all"} value={value}>{value ? titleCase(value) : "All activities"}</option>)}</select></Field>
      <div className="filter-actions"><Button variant="secondary" type="submit">Apply range</Button></div>
    </form></Panel>
    {insights.isLoading ? <Loading label="Calculating contribution evidence…" /> : insights.error ? <ErrorState error={insights.error} retry={() => void insights.refetch()} /> : insights.data && <>
      <ContributionDashboard members={insights.data.members} rangeStart={insights.data.range_start} rangeEnd={insights.data.range_end} eventType={insights.data.event_type} />
      <Panel labelledBy="summary-heading"><div className="section-heading"><h3 id="summary-heading">Member summary</h3><span>{insights.data.range_start} to {insights.data.range_end}</span></div><div className="table-wrap"><table><thead><tr><th scope="col">Member</th><th scope="col">Role</th><th scope="col">Recorded actions</th><th scope="col">Tasks completed</th><th scope="col">Comments</th><th scope="col">Meetings accepted</th></tr></thead><tbody>{insights.data.members.map((member) => <tr key={member.user_id}><th scope="row">{member.display_name}</th><td><StatusBadge value={member.role} /></td><td>{member.total_events}</td><td>{member.completed_tasks}</td><td>{member.comments}</td><td>{member.accepted_meetings}</td></tr>)}</tbody></table></div></Panel>
      <Panel labelledBy="timeline-heading"><div className="section-heading"><h3 id="timeline-heading">Activity timeline</h3>{insights.data.events_truncated && <span>Showing the latest 200</span>}</div>{!insights.data.events.length ? <EmptyState title="No activity in this range">Change the date range or activity filter.</EmptyState> : <ol className="timeline">{insights.data.events.map((event) => <li key={event.id}><span className="timeline__dot" aria-hidden="true" /><div><strong>{event.actor.display_name}</strong> {titleCase(event.event_type).toLowerCase()}<time dateTime={event.occurred_at}>{formatDate(event.occurred_at)}</time></div></li>)}</ol>}</Panel>
    </>}
    {exports.error && <ErrorState error={exports.error} retry={() => void exports.refetch()} />}
    {exports.isLoading && <Loading label="Loading recent exports…" />}
    {relevantExports.length > 0 && <Panel labelledBy="exports-heading"><h3 id="exports-heading">Recent exports</h3><div className="compact-list">{relevantExports.map((job) => <div className="compact-row" key={job.id}><span><strong>{job.format.toUpperCase()} evidence</strong><small>{job.range_start} to {job.range_end} · {formatDate(job.created_at)}{job.status === "failed" && ` · ${job.error_message || "Generation failed."}`}</small></span><span className="row-actions"><StatusBadge value={job.status} />{job.status === "failed" && <Button variant="quiet" disabled={createExport.isPending} onClick={() => createExport.mutate({ format: job.format, range_start: job.range_start, range_end: job.range_end })}>Retry</Button>}{job.download_url && <a className="button button--quiet" href={job.download_url}>Download</a>}</span></div>)}</div></Panel>}
  </div>;
}
