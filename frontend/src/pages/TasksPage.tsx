import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import { accountApi, membershipApi, projectApi, taskApi, type TaskFilters } from "../api/resources";
import type { TaskPriority, TaskStatus } from "../api/types";
import { scheduleDebounced } from "../app/debounce";
import { formatDate, parseOptionalDateTime, titleCase } from "../app/format";
import { Button, EmptyState, ErrorState, Field, Loading, Panel, StatusBadge } from "../components/UI";

const columns: TaskStatus[] = ["todo", "in_progress", "blocked", "done"];

export default function TasksPage() {
  const { projectId = "" } = useParams();
  const client = useQueryClient();
  const [filters, setFilters] = useState<TaskFilters>({});
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [showFilters, setShowFilters] = useState(() => !window.matchMedia("(max-width: 760px)").matches);
  const [blockingTaskId, setBlockingTaskId] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const tasks = useQuery({ queryKey: ["tasks", projectId, filters], queryFn: () => taskApi.list(projectId, filters), enabled: Boolean(projectId) });
  const members = useQuery({ queryKey: ["memberships", projectId], queryFn: () => membershipApi.list(projectId), enabled: Boolean(projectId) });
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => projectApi.get(projectId), enabled: Boolean(projectId) });
  const me = useQuery({ queryKey: ["me"], queryFn: accountApi.me, staleTime: 60_000 });
  const refresh = () => client.invalidateQueries({ queryKey: ["tasks", projectId] });
  const create = useMutation({ mutationFn: taskApi.create, onSuccess: async () => { await refresh(); setShowCreate(false); setError(""); setMessage("Task created."); }, onError: (value) => { setMessage(""); setError(errorMessage(value)); } });
  const transition = useMutation({ mutationFn: ({ id, status, note }: { id: string; status: TaskStatus; note?: string }) => taskApi.transition(id, status, note), onSuccess: async () => { await refresh(); setBlockingTaskId(null); setError(""); setMessage("Task status updated."); }, onError: (value) => { setMessage(""); setError(errorMessage(value)); } });
  const counts = useMemo(() => Object.fromEntries(columns.map((status) => [status, tasks.data?.results.filter((task) => task.status === status).length ?? 0])), [tasks.data]);
  const currentRole = members.data?.results.find((member) => member.user.id === me.data?.user.id)?.role;
  const isProjectArchived = Boolean(project.data?.archived_at);

  useEffect(
    () => scheduleDebounced(() => {
      const q = search.trim();
      setFilters((current) => (current.q ?? "") === q ? current : { ...current, q });
    }),
    [search],
  );

  const submitCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError(""); setMessage("");
    const data = new FormData(event.currentTarget);
    const dueAt = parseOptionalDateTime(String(data.get("due_at")));
    if (dueAt === undefined) { setError("Choose a valid due date and time."); return; }
    create.mutate({ project: projectId, title: String(data.get("title")), description: String(data.get("description")), priority: String(data.get("priority")) as TaskPriority, due_at: dueAt });
  };
  const submitFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setFilters(Object.fromEntries([...data.entries()].map(([key, value]) => [key, String(value)])) as TaskFilters);
  };
  const move = (id: string, status: TaskStatus) => {
    setError(""); setMessage("");
    if (status === "blocked") { setBlockingTaskId(id); return; }
    setBlockingTaskId(null);
    transition.mutate({ id, status, note: "" });
  };
  const submitBlocker = (id: string, event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const note = String(new FormData(event.currentTarget).get("blocker_note")).trim();
    if (note.length < 3) { setError("Describe the blocker using at least 3 characters."); return; }
    transition.mutate({ id, status: "blocked", note });
  };

  return (
    <div className="page-stack">
      <div className="page-heading"><div><p className="eyebrow">Delivery board</p><h2>Tasks</h2><p>See ownership, deadlines and blockers without chasing updates.</p></div><span className="row-actions"><Button type="button" variant="secondary" aria-expanded={showFilters} onClick={() => setShowFilters((value) => !value)}>{showFilters ? "Hide filters" : "Filters"}</Button>{!isProjectArchived && <Button onClick={() => setShowCreate((value) => !value)}>{showCreate ? "Close form" : "New task"}</Button>}</span></div>
      {(message || error) && <p className={error ? "notice notice--error" : "notice"} role={error ? "alert" : "status"}>{error || message}</p>}
      {isProjectArchived && <p className="notice" role="status">This project is archived. Tasks remain available as read-only history.</p>}
      {showCreate && !isProjectArchived && <Panel labelledBy="create-task-heading"><h3 id="create-task-heading">Create task</h3><form className="form-grid" onSubmit={submitCreate}>
        <Field label="Task title"><input name="title" required minLength={3} maxLength={120} autoFocus /></Field>
        <Field label="Priority"><select name="priority" defaultValue="medium"><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="urgent">Urgent</option></select></Field>
        <Field label="Due date and time"><input name="due_at" type="datetime-local" /></Field>
        <Field label="Description"><textarea name="description" rows={3} maxLength={4000} /></Field>
        <div className="form-actions"><Button type="submit" disabled={create.isPending}>{create.isPending ? "Creating…" : "Create task"}</Button></div>
      </form></Panel>}

      {showFilters && <Panel labelledBy="filter-heading"><h3 id="filter-heading" className="sr-only">Filter tasks</h3><form className="filter-bar" onSubmit={submitFilters}>
        <Field label="Search" hint="Results update 300 ms after you stop typing."><input name="q" type="search" placeholder="Title or description" value={search} onChange={(event) => setSearch(event.target.value)} /></Field>
        <Field label="Status"><select name="status"><option value="">All statuses</option>{columns.map((value) => <option key={value} value={value}>{titleCase(value)}</option>)}</select></Field>
        <Field label="Priority"><select name="priority"><option value="">All priorities</option>{["low", "medium", "high", "urgent"].map((value) => <option key={value} value={value}>{titleCase(value)}</option>)}</select></Field>
        <Field label="Record state"><select name="scope" defaultValue="active"><option value="active">Current tasks</option><option value="archived">Archived tasks</option><option value="all">All records</option></select></Field>
        <Field label="Assignee"><select name="assignee"><option value="">Anyone</option>{members.data?.results.map((member) => <option key={member.user.id} value={member.user.id}>{member.user.display_name}</option>)}</select></Field>
        <Field label="Due date"><select name="due"><option value="">Any due date</option><option value="overdue">Overdue</option><option value="upcoming">Upcoming</option><option value="none">No due date</option></select></Field>
        <div className="filter-actions"><Button type="submit" variant="secondary">Apply</Button><Button type="button" variant="quiet" onClick={(event) => { event.currentTarget.form?.reset(); setSearch(""); setFilters({}); }}>Clear</Button></div>
      </form></Panel>}

      {tasks.isFetching && !tasks.isLoading && <p className="muted" role="status">Updating task results…</p>}

      {tasks.isLoading || members.isLoading || me.isLoading || project.isLoading ? <Loading label="Loading tasks…" /> : tasks.error || members.error || me.error || project.error ? <ErrorState error={tasks.error ?? members.error ?? me.error ?? project.error} retry={() => { void tasks.refetch(); void members.refetch(); void me.refetch(); void project.refetch(); }} /> : !tasks.data?.count ? <EmptyState title="No tasks match">{filters.scope === "archived" ? "No archived tasks match these filters." : isProjectArchived ? "No current task records remain in this archived project. Choose Archived tasks to review retained evidence." : "Create a task or clear the current filters."}</EmptyState> : (
        <div className="task-board">
          {columns.map((status) => <section className="task-column" key={status} aria-labelledby={`column-${status}`}>
            <div className="task-column__heading"><h3 id={`column-${status}`}>{titleCase(status)}</h3><span>{counts[status]}</span></div>
            <div className="task-column__items">{tasks.data.results.filter((task) => task.status === status).map((task) => {
              const isTaskArchived = Boolean(task.archived_at);
              const canTransition = !isProjectArchived && !isTaskArchived && (currentRole === "owner" || task.assignees.some((user) => user.id === me.data?.user.id));
              return <article className="task-card" key={task.id}>
              <div className="task-card__meta"><span className="heading-badges"><StatusBadge value={task.priority} />{isTaskArchived && <StatusBadge value="archived" />}</span><span>{task.comment_count} comment{task.comment_count === 1 ? "" : "s"}</span></div>
              <h4><Link to={`/app/projects/${projectId}/tasks/${task.id}/`}>{task.title}</Link></h4>
              <p>{task.description || "No description."}</p>
              <div className="avatar-stack" aria-label={task.assignees.length ? `Assigned to ${task.assignees.map((user) => user.display_name).join(", ")}` : "Unassigned"}>{task.assignees.length ? task.assignees.map((user) => <span className="avatar avatar--small" title={user.display_name} key={user.id}>{user.display_name.slice(0, 1).toUpperCase()}</span>) : <span className="muted">Unassigned</span>}</div>
              <small>{formatDate(task.due_at)}</small>
              {canTransition ? <><label className="field field--compact"><span className="sr-only">Move {task.title}</span><select value={blockingTaskId === task.id ? "blocked" : task.status} title="Change task status" onChange={(event) => move(task.id, event.target.value as TaskStatus)} disabled={transition.isPending}>{columns.map((value) => <option key={value} value={value}>{titleCase(value)}</option>)}</select></label>
              {blockingTaskId === task.id ? <form className="task-card__blocker" onSubmit={(event) => submitBlocker(task.id, event)}><Field label="Blocker note"><textarea name="blocker_note" required minLength={3} maxLength={500} rows={3} defaultValue={task.blocker_note} autoFocus /></Field><div className="form-actions"><Button type="submit" disabled={transition.isPending}>{transition.isPending ? "Saving…" : "Mark blocked"}</Button><Button type="button" variant="quiet" disabled={transition.isPending} onClick={() => setBlockingTaskId(null)}>Cancel</Button></div></form> : task.status === "blocked" ? <Button type="button" variant="quiet" onClick={() => setBlockingTaskId(task.id)}>Edit blocker note</Button> : null}</> : <span className="task-card__read-only">{isTaskArchived ? "Archived · read-only evidence" : isProjectArchived ? "Project archived · read-only" : "Only an assignee or owner can change status"}</span>}
            </article>;
            })}</div>
          </section>)}
        </div>
      )}
    </div>
  );
}
