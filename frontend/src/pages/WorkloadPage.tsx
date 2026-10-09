import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { productivityApi as api, type DueBuckets } from "../api/productivity";
import { formatDate } from "../app/format";
import { ErrorState, Loading, Panel } from "../components/UI";
import "./productivity.css";

function DueDistribution({ due }: { due: DueBuckets }) {
  const total = due.overdue + due.next_7_days + due.later + due.no_deadline;
  return <div><div className="productivity-due-bar" aria-hidden="true">{(["overdue", "next_7_days", "later", "no_deadline"] as const).map(key => due[key] > 0 && <span key={key} className={`productivity-due-${key}`} style={{ width: `${due[key] / total * 100}%` }} />)}</div><p className="muted">{due.overdue} overdue · {due.next_7_days} next 7 days · {due.later} later · {due.no_deadline} without deadline</p></div>;
}

export default function WorkloadPage() {
  const { projectId = "" } = useParams();
  const workload = useQuery({ queryKey: ["workload", projectId], queryFn: () => api.workload(projectId), enabled: Boolean(projectId) });
  if (workload.isPending) return <Loading label="Loading team workload" />;
  if (workload.error || !workload.data) return <ErrorState error={workload.error} retry={() => void workload.refetch()} />;
  const data = workload.data;
  return <div className="page-stack productivity"><div><h1>Team workload</h1><p>{data.project.name} · <Link to={`/app/projects/${projectId}/tasks`}>Task board</Link></p></div><Panel><h2>Recorded work and upcoming tasks</h2><p>{data.method}</p><p className="muted">As of {formatDate(data.as_of)} · Total recorded work {(data.actual_seconds / 3600).toFixed(2)} h. An estimate is planning information, and logged time does not establish contribution quality.</p></Panel>
    {data.members.map(member => <Panel key={member.user_id}><h2>{member.name}{!member.current_member && <span className="muted"> · former member</span>}</h2><dl className="productivity-metrics"><div><dt>Open assigned tasks</dt><dd>{member.open_tasks}</dd></div><div><dt>Share of open-task estimates</dt><dd>{member.assigned_estimate_hours} h</dd></div><div><dt>Self-recorded actual time</dt><dd>{(member.actual_seconds / 3600).toFixed(2)} h</dd></div></dl><DueDistribution due={member.due} /></Panel>)}
    <Panel><h2>Unassigned work</h2><p>{data.unassigned.open_tasks} open tasks · {data.unassigned.estimate_hours} estimated hours</p><DueDistribution due={data.unassigned.due} /></Panel>
  </div>;
}
