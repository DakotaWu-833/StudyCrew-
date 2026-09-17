import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import { accountApi, commentApi, membershipApi, projectApi, taskApi } from "../api/resources";
import type { TaskPriority, TaskStatus } from "../api/types";
import { formatDate, parseOptionalDateTime, titleCase, toDateTimeLocal } from "../app/format";
import { Button, ConfirmAction, EmptyState, ErrorState, Field, Loading, Panel, StatusBadge } from "../components/UI";

const statuses: TaskStatus[] = ["todo", "in_progress", "blocked", "done"];

export default function TaskDetailPage() {
  const { projectId = "", taskId = "" } = useParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [selectedAssignees, setSelectedAssignees] = useState<string[]>([]);
  const [mentionedUsers, setMentionedUsers] = useState<string[]>([]);
  const [pendingStatus, setPendingStatus] = useState<TaskStatus | null>(null);
  const [editingCommentId, setEditingCommentId] = useState<string | null>(null);
  const [reportingCommentId, setReportingCommentId] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const task = useQuery({ queryKey: ["task", taskId], queryFn: () => taskApi.get(taskId), enabled: Boolean(taskId) });
  const taskProjectId = task.data?.project ?? "";
  const comments = useQuery({ queryKey: ["comments", taskId], queryFn: () => commentApi.list(taskId), enabled: Boolean(taskId) });
  const members = useQuery({ queryKey: ["memberships", taskProjectId], queryFn: () => membershipApi.list(taskProjectId), enabled: Boolean(taskProjectId) });
  const project = useQuery({ queryKey: ["project", taskProjectId], queryFn: () => projectApi.get(taskProjectId), enabled: Boolean(taskProjectId) });
  const me = useQuery({ queryKey: ["me"], queryFn: accountApi.me });
  useEffect(() => setSelectedAssignees(task.data?.assignees.map((user) => user.id) ?? []), [task.data?.assignees]);
  useEffect(() => {
    if (taskProjectId && taskProjectId !== projectId) navigate(`/app/projects/${taskProjectId}/tasks/${taskId}/`, { replace: true });
  }, [navigate, projectId, taskId, taskProjectId]);

  const fail = (value: unknown) => { setMessage(""); setError(errorMessage(value)); };
  const refreshTask = () => Promise.all([client.invalidateQueries({ queryKey: ["task", taskId] }), client.invalidateQueries({ queryKey: ["tasks", taskProjectId] })]);
  const update = useMutation({ mutationFn: (data: { title: string; description: string; priority: TaskPriority; due_at: string | null }) => taskApi.update(taskId, data), onSuccess: async () => { await refreshTask(); setEditing(false); setError(""); setMessage("Task details saved."); }, onError: fail });
  const assign = useMutation({ mutationFn: () => taskApi.setAssignees(taskId, selectedAssignees), onSuccess: async () => { await refreshTask(); setError(""); setMessage("Assignees updated."); }, onError: fail });
  const transition = useMutation({ mutationFn: ({ status, blocker_note }: { status: TaskStatus; blocker_note: string }) => taskApi.transition(taskId, status, blocker_note), onSuccess: async () => { await refreshTask(); setPendingStatus(null); setError(""); setMessage("Task status updated."); }, onError: fail });
  const archive = useMutation({ mutationFn: () => taskApi.archive(taskId), onSuccess: async () => { await client.invalidateQueries({ queryKey: ["tasks", taskProjectId] }); navigate(`/app/projects/${taskProjectId}/tasks/`); }, onError: fail });
  const addComment = useMutation({ mutationFn: (body: string) => commentApi.create(taskId, body, mentionedUsers), onSuccess: async () => { await Promise.all([comments.refetch(), refreshTask()]); setMentionedUsers([]); setError(""); setMessage("Comment added."); }, onError: fail });
  const editComment = useMutation({ mutationFn: ({ id, body }: { id: string; body: string }) => commentApi.update(id, body), onSuccess: async () => { await comments.refetch(); setEditingCommentId(null); setError(""); setMessage("Comment updated."); }, onError: fail });
  const deleteComment = useMutation({ mutationFn: commentApi.remove, onSuccess: async () => { await Promise.all([comments.refetch(), refreshTask()]); setError(""); setMessage("Comment removed."); }, onError: fail });
  const reportComment = useMutation({ mutationFn: ({ id, details }: { id: string; details: string }) => commentApi.report(id, "other", details), onSuccess: () => { setReportingCommentId(null); setError(""); setMessage("Report sent to site moderators."); }, onError: fail });

  if (task.isLoading || comments.isLoading || members.isLoading || project.isLoading || me.isLoading) return <Loading label="Loading task…" />;
  if (task.error || comments.error || members.error || project.error || me.error) return <ErrorState error={task.error ?? comments.error ?? members.error ?? project.error ?? me.error} retry={() => { void task.refetch(); void comments.refetch(); void members.refetch(); void project.refetch(); void me.refetch(); }} />;
  if (!task.data) return null;
  const currentMembership = members.data?.results.find((member) => member.user.id === me.data?.user.id);
  const isTaskArchived = Boolean(task.data.archived_at);
  const isProjectArchived = Boolean(project.data?.archived_at);
  const isReadOnly = isTaskArchived || isProjectArchived;
  const canTransition = currentMembership?.role === "owner" || task.data.assignees.some((user) => user.id === me.data?.user.id);
  const canModerateComments = currentMembership?.role === "owner" || currentMembership?.role === "facilitator";

  const submitEdit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    const dueAt = parseOptionalDateTime(String(data.get("due_at")));
    if (dueAt === undefined) { setMessage(""); setError("Choose a valid due date and time."); return; }
    update.mutate({ title: String(data.get("title")), description: String(data.get("description")), priority: String(data.get("priority")) as TaskPriority, due_at: dueAt });
  };
  const submitComment = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const form = event.currentTarget; const body = String(new FormData(form).get("body"));
    addComment.mutate(body, { onSuccess: () => form.reset() });
  };
  const changeStatus = (status: TaskStatus) => {
    setError(""); setMessage("");
    if (status === "blocked") { setPendingStatus("blocked"); return; }
    setPendingStatus(null);
    transition.mutate({ status, blocker_note: "" });
  };
  const submitBlocker = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const blockerNote = String(new FormData(event.currentTarget).get("blocker_note")).trim();
    if (blockerNote.length < 3) { setError("Describe the blocker using at least 3 characters."); return; }
    transition.mutate({ status: "blocked", blocker_note: blockerNote });
  };

  return (
    <div className="page-stack">
      <Link className="back-link" to={`/app/projects/${taskProjectId}/tasks/`}>← Back to task board</Link>
      {(message || error) && <p className={error ? "notice notice--error" : "notice"} role={error ? "alert" : "status"}>{error || message}</p>}
      {isReadOnly && <p className="notice" role="status">{isTaskArchived ? "This task is archived." : "Its project is archived."} Details and discussion remain available as read-only evidence.</p>}
      <div className="page-heading"><div><div className="heading-badges"><StatusBadge value={task.data.status} /><StatusBadge value={task.data.priority} />{isTaskArchived && <StatusBadge value="archived" />}</div><h2>{task.data.title}</h2><p>Created by {task.data.created_by.display_name} · updated {formatDate(task.data.updated_at)}</p></div>{!isReadOnly && <Button variant="secondary" onClick={() => setEditing((value) => !value)}>{editing ? "Cancel" : "Edit details"}</Button>}</div>

      {task.data.status === "blocked" && <div className="blocker" role="note"><strong>Blocked:</strong> {task.data.blocker_note}</div>}
      <div className="detail-grid">
        <Panel labelledBy="details-heading"><h3 id="details-heading">Details</h3>{editing ? <form className="form-grid" onSubmit={submitEdit}>
          <Field label="Title"><input name="title" required minLength={3} maxLength={120} defaultValue={task.data.title} /></Field>
          <Field label="Priority"><select name="priority" defaultValue={task.data.priority}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="urgent">Urgent</option></select></Field>
          <Field label="Due date"><input name="due_at" type="datetime-local" defaultValue={toDateTimeLocal(task.data.due_at)} /></Field>
          <Field label="Description"><textarea name="description" rows={5} maxLength={4000} defaultValue={task.data.description} /></Field>
          <div className="form-actions"><Button type="submit" disabled={update.isPending}>Save details</Button></div>
        </form> : <><p className="prose">{task.data.description || "No description has been added."}</p><dl className="key-values"><div><dt>Due</dt><dd>{formatDate(task.data.due_at)}</dd></div><div><dt>Completed</dt><dd>{formatDate(task.data.completed_at)}</dd></div></dl></>}</Panel>

        <aside className="page-stack">
          <Panel labelledBy="status-heading"><h3 id="status-heading">Status</h3><Field label="Current status" hint={!isReadOnly && !canTransition ? "Only an assignee or the project owner can change status." : undefined}><select value={pendingStatus ?? task.data.status} onChange={(event) => changeStatus(event.target.value as TaskStatus)} disabled={isReadOnly || !canTransition || transition.isPending}>{statuses.map((value) => <option key={value} value={value}>{titleCase(value)}</option>)}</select></Field>{!isReadOnly && canTransition && pendingStatus === "blocked" ? <form className="status-transition-form" onSubmit={submitBlocker}><Field label="What is blocking this task?" hint="Give teammates enough detail to unblock the work."><textarea name="blocker_note" required minLength={3} maxLength={500} rows={3} defaultValue={task.data.blocker_note} autoFocus /></Field><div className="form-actions"><Button type="submit" disabled={transition.isPending}>{transition.isPending ? "Saving…" : "Mark blocked"}</Button><Button type="button" variant="quiet" disabled={transition.isPending} onClick={() => setPendingStatus(null)}>Cancel</Button></div></form> : !isReadOnly && canTransition && task.data.status === "blocked" ? <Button type="button" variant="quiet" onClick={() => setPendingStatus("blocked")}>Update blocker note</Button> : null}</Panel>
          <Panel labelledBy="assignees-heading"><h3 id="assignees-heading">Assignees</h3><fieldset className="check-list" disabled={isReadOnly}><legend className="sr-only">Choose assignees</legend>{members.data?.results.map((member) => <label key={member.user.id}><input type="checkbox" checked={selectedAssignees.includes(member.user.id)} onChange={(event) => setSelectedAssignees((current) => event.target.checked ? [...current, member.user.id] : current.filter((id) => id !== member.user.id))} /> <span>{member.user.display_name}</span></label>)}</fieldset>{!isReadOnly && <Button variant="secondary" onClick={() => assign.mutate()} disabled={assign.isPending}>Save assignees</Button>}</Panel>
        </aside>
      </div>

      <Panel labelledBy="comments-heading"><div className="section-heading"><h3 id="comments-heading">Discussion</h3><span>{task.data.comment_count} comment{task.data.comment_count === 1 ? "" : "s"}</span></div>
        {!isReadOnly && <form className="comment-form" onSubmit={submitComment}><Field label="Add a comment"><textarea name="body" required maxLength={2000} rows={3} /></Field><fieldset className="mention-list"><legend>Notify teammates mentioned by this comment <span>(optional)</span></legend>{members.data?.results.filter((member) => member.user.id !== me.data?.user.id).map((member) => <label key={member.user.id}><input type="checkbox" checked={mentionedUsers.includes(member.user.id)} onChange={(event) => setMentionedUsers((current) => event.target.checked ? [...current, member.user.id] : current.filter((id) => id !== member.user.id))} /> {member.user.display_name}</label>)}</fieldset><Button type="submit" disabled={addComment.isPending}>{addComment.isPending ? "Posting…" : "Post comment"}</Button></form>}
        {!comments.data?.count ? <EmptyState title="No discussion yet">{isReadOnly ? "No discussion was recorded before this workspace became read-only." : "Add context, a decision or a useful progress update."}</EmptyState> : <div className="comment-list">{comments.data.results.map((comment) => {
          const isEditingComment = editingCommentId === comment.id;
          const isReportingComment = reportingCommentId === comment.id;
          const ownsComment = comment.author.id === me.data?.user.id;
          return <article className="comment" key={comment.id}>
            <span className="avatar" aria-hidden="true">{comment.author.display_name.slice(0, 1).toUpperCase()}</span><div className="comment__body"><div><strong>{comment.author.display_name}</strong><time dateTime={comment.created_at}>{formatDate(comment.created_at)}</time>{comment.edited_at && <small>edited</small>}</div><p>{comment.is_deleted ? <em>Comment removed</em> : comment.body}</p>{!isReadOnly && !comment.is_deleted && !isEditingComment && !isReportingComment && <span className="row-actions">{(ownsComment || canModerateComments) && <><Button variant="quiet" onClick={() => { setReportingCommentId(null); setEditingCommentId(comment.id); }}>{ownsComment ? "Edit" : "Moderate"}</Button><ConfirmAction triggerLabel={ownsComment ? "Delete" : "Remove"} triggerVariant="quiet" confirmLabel={ownsComment ? "Delete comment" : "Remove comment"} message={ownsComment ? "Delete this comment? Its audit record will be retained." : "Remove this teammate's comment as a project moderator? The action remains in the audit record."} busy={deleteComment.isPending} onConfirm={() => deleteComment.mutate(comment.id)} /></>}{!ownsComment && <Button variant="quiet" onClick={() => { setEditingCommentId(null); setReportingCommentId(comment.id); }}>Report</Button>}</span>}
              {isEditingComment && <form className="comment-inline-form" onSubmit={(event) => { event.preventDefault(); editComment.mutate({ id: comment.id, body: String(new FormData(event.currentTarget).get("body")).trim() }); }}><Field label={ownsComment ? "Edit comment" : "Moderate comment"} hint={ownsComment ? undefined : "This change is permitted by your project role and remains attributable to you."}><textarea name="body" required maxLength={2000} rows={3} defaultValue={comment.body} autoFocus /></Field><div className="form-actions"><Button type="submit" disabled={editComment.isPending}>{editComment.isPending ? "Saving…" : ownsComment ? "Save comment" : "Save moderation"}</Button><Button type="button" variant="quiet" disabled={editComment.isPending} onClick={() => setEditingCommentId(null)}>Cancel</Button></div></form>}
              {isReportingComment && <form className="comment-inline-form" onSubmit={(event) => { event.preventDefault(); reportComment.mutate({ id: comment.id, details: String(new FormData(event.currentTarget).get("details")).trim() }); }}><Field label="Why should a moderator review this comment?" hint="Your report is visible only to site moderators."><textarea name="details" required minLength={3} maxLength={500} rows={3} autoFocus /></Field><div className="form-actions"><Button type="submit" disabled={reportComment.isPending}>{reportComment.isPending ? "Sending…" : "Send report"}</Button><Button type="button" variant="quiet" disabled={reportComment.isPending} onClick={() => setReportingCommentId(null)}>Cancel</Button></div></form>}
            </div>
          </article>;
        })}</div>}
      </Panel>
      {!isReadOnly && <Panel className="danger-zone" labelledBy="archive-task-heading"><h3 id="archive-task-heading">Archive task</h3><p>This removes the task from the active board but preserves the audit history.</p><ConfirmAction triggerLabel="Archive task" confirmLabel="Archive task" message="Archive this task? Details, comments and audit history will remain available as read-only evidence." busy={archive.isPending} onConfirm={() => archive.mutate()} /></Panel>}
    </div>
  );
}
