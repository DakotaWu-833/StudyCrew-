import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { errorMessage, fieldErrors } from "../api/client";
import { accountApi, membershipApi, projectApi, taskApi, type TaskFilters } from "../api/resources";
import type { TaskPriority, TaskStatus } from "../api/types";
import { scheduleDebounced } from "../app/debounce";
import { formatDate, parseOptionalDateTime, titleCase } from "../app/format";
import { Button, EmptyState, ErrorState, Field, FloatingPanel, Loading, StatusBadge } from "../components/UI";

const columns: TaskStatus[] = ["todo", "in_progress", "blocked", "done"];

export default function TasksPage() {
  const { projectId = "" } = useParams();
  const client = useQueryClient();
  const [filters, setFilters] = useState<TaskFilters>({});
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const [view, setView] = useState<"board" | "list">("board");
  const [createDirty, setCreateDirty] = useState(false);
  const [blockerDirty, setBlockerDirty] = useState(false);
  const [blockingTaskId, setBlockingTaskId] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const tasks = useQuery({
    queryKey: ["tasks", projectId, filters],
    queryFn: () => taskApi.list(projectId, filters),
    enabled: Boolean(projectId),
    // A filter update may retain this project's cards, never another project's data.
    placeholderData: (previous, query) => query?.queryKey[1] === projectId ? previous : undefined,
  });
  const members = useQuery({ queryKey: ["memberships", projectId], queryFn: () => membershipApi.list(projectId), enabled: Boolean(projectId) });
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => projectApi.get(projectId), enabled: Boolean(projectId) });
  const me = useQuery({ queryKey: ["me"], queryFn: accountApi.me, staleTime: 60_000 });
  const refresh = () => client.invalidateQueries({ queryKey: ["tasks", projectId] });
  const create = useMutation({ mutationFn: taskApi.create, onSuccess: async () => { await refresh(); setShowCreate(false); setCreateDirty(false); setError(""); setMessage("Task created."); }, onError: (value) => {
    setMessage(""); setError(errorMessage(value));
    const firstField = Object.keys(fieldErrors(value))[0];
    [...document.querySelectorAll<HTMLElement>("dialog [name]")].find((field) => field.getAttribute("name") === firstField)?.focus();
  } });
  const transition = useMutation({ mutationFn: ({ id, status, note }: { id: string; status: TaskStatus; note?: string }) => taskApi.transition(id, status, note), onSuccess: async () => { await refresh(); setBlockingTaskId(null); setError(""); setMessage("Task status updated."); }, onError: (value) => { setMessage(""); setError(errorMessage(value)); } });
  const counts = useMemo(() => Object.fromEntries(columns.map((status) => [status, tasks.data?.results.filter((task) => task.status === status).length ?? 0])), [tasks.data]);
  const currentRole = members.data?.results.find((member) => member.user.id === me.data?.user.id)?.role;
  const isProjectArchived = Boolean(project.data?.archived_at);
  const blockingTask = tasks.data?.results.find((task) => task.id === blockingTaskId);
  const createErrors = fieldErrors(create.error);
  const activeFilters = Object.entries(filters).filter(([, value]) => Boolean(value)).filter(([key, value]) => key !== "scope" || value !== "active");
  const clearFilters = () => { setSearch(""); setFilters({}); setShowFilters(false); };
  const filterLabel = (key: string, value: string) => {
    if (key === "q") return `Search: ${value}`;
    if (key === "assignee") return `Assignee: ${members.data?.results.find((member) => member.user.id === value)?.user.display_name ?? "Selected member"}`;
    return `${key === "scope" ? "Records" : titleCase(key)}: ${titleCase(value)}`;
  };

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
    setShowFilters(false);
  };
  const move = (id: string, status: TaskStatus) => {
    setError(""); setMessage("");
    if (status === "blocked") { setBlockerDirty(false); setBlockingTaskId(id); return; }
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
      <div className="page-heading"><div><p className="eyebrow">Delivery board</p><h2>Tasks</h2><p>See ownership, deadlines and blockers without chasing updates.</p></div><span className="row-actions"><Button type="button" variant="secondary" aria-expanded={showFilters} onClick={() => { setShowFilters((value) => !value); setShowCreate(false); setBlockingTaskId(null); }}>{showFilters ? "Close filters" : "Filters"}</Button>{!isProjectArchived && <Button type="button" aria-expanded={showCreate} onClick={() => { create.reset(); setError(""); setCreateDirty(false); setShowCreate(true); setShowFilters(false); setBlockingTaskId(null); }}>New task</Button>}</span></div>
      {(message || error) && <p className={error ? "notice notice--error" : "notice"} role={error ? "alert" : "status"}>{error || message}</p>}
      {isProjectArchived && <p className="notice" role="status">This project is archived. Tasks remain available as read-only history.</p>}
      {showCreate && !isProjectArchived && <FloatingPanel title="Create task" busy={create.isPending} dirty={createDirty} onDismiss={() => setShowCreate(false)}><form className="form-grid" onSubmit={submitCreate} onChange={() => setCreateDirty(true)}>
        <Field label="Task title" error={createErrors.title}><input name="title" required minLength={3} maxLength={120} autoFocus /></Field>
        <Field label="Priority" error={createErrors.priority}><select name="priority" defaultValue="medium"><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="urgent">Urgent</option></select></Field>
        <Field label="Due date and time" error={createErrors.due_at}><input name="due_at" type="datetime-local" /></Field>
        <Field label="Description" error={createErrors.description}><textarea name="description" rows={3} maxLength={4000} /></Field>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="form-actions"><Button type="submit" disabled={create.isPending}>{create.isPending ? "Creating…" : "Create task"}</Button></div>
      </form></FloatingPanel>}

      {showFilters && <FloatingPanel title="Filter tasks" onDismiss={() => setShowFilters(false)}><form className="filter-bar" onSubmit={submitFilters}>
        <Field label="Search" hint="Results update 300 ms after you stop typing."><input name="q" type="search" placeholder="Title or description" value={search} onChange={(event) => setSearch(event.target.value)} /></Field>
        <Field label="Status"><select name="status" defaultValue={filters.status ?? ""}><option value="">All statuses</option>{columns.map((value) => <option key={value} value={value}>{titleCase(value)}</option>)}</select></Field>
        <Field label="Priority"><select name="priority" defaultValue={filters.priority ?? ""}><option value="">All priorities</option>{["low", "medium", "high", "urgent"].map((value) => <option key={value} value={value}>{titleCase(value)}</option>)}</select></Field>
        <Field label="Record state"><select name="scope" defaultValue={filters.scope ?? "active"}><option value="active">Current tasks</option><option value="archived">Archived tasks</option><option value="all">All records</option></select></Field>
        <Field label="Assignee"><select name="assignee" defaultValue={filters.assignee ?? ""}><option value="">Anyone</option>{members.data?.results.map((member) => <option key={member.user.id} value={member.user.id}>{member.user.display_name}</option>)}</select></Field>
        <Field label="Due date"><select name="due" defaultValue={filters.due ?? ""}><option value="">Any due date</option><option value="overdue">Overdue</option><option value="upcoming">Upcoming</option><option value="none">No due date</option></select></Field>
        <div className="filter-actions"><Button type="submit" variant="secondary">Apply</Button><Button type="button" variant="quiet" onClick={clearFilters}>Clear</Button></div>
      </form></FloatingPanel>}

      <div className="task-results-toolbar">
        <div className="task-filter-chips" aria-label="Applied task filters">
          {activeFilters.length ? <><span className="task-filter-count">{activeFilters.length} filter{activeFilters.length === 1 ? "" : "s"}</span>{activeFilters.map(([key, value]) => <button key={key} type="button" className="task-filter-chip" aria-label={`Remove ${filterLabel(key, value)}`} onClick={() => {
            if (key === "q") setSearch("");
            setFilters((current) => { const next = { ...current }; delete next[key as keyof TaskFilters]; return next; });
          }}>{filterLabel(key, value)} <span aria-hidden="true">×</span></button>)}<Button type="button" variant="quiet" onClick={clearFilters}>Clear all</Button></> : <span className="muted">All current tasks</span>}
        </div>
        <div className="task-view-toggle" role="group" aria-label="Task view">
          <Button type="button" variant="quiet" aria-pressed={view === "board"} onClick={() => setView("board")}>Board</Button>
          <Button type="button" variant="quiet" aria-pressed={view === "list"} onClick={() => setView("list")}>List</Button>
        </div>
      </div>
      <p className="task-result-status muted" role="status" aria-live="polite">{tasks.isFetching && tasks.data ? "Updating task results…" : tasks.data ? `${tasks.data.count} matching task${tasks.data.count === 1 ? "" : "s"}` : ""}</p>

      {tasks.isLoading || members.isLoading || me.isLoading || project.isLoading ? <Loading label="Loading tasks…" /> : tasks.error || members.error || me.error || project.error ? <ErrorState error={tasks.error ?? members.error ?? me.error ?? project.error} retry={() => { void tasks.refetch(); void members.refetch(); void me.refetch(); void project.refetch(); }} /> : !tasks.data?.count ? <EmptyState title="No tasks match">{filters.scope === "archived" ? "No archived tasks match these filters." : isProjectArchived ? "No current task records remain in this archived project. Choose Archived tasks to review retained evidence." : "Create a task or clear the current filters."}</EmptyState> : (
        <div className={`task-board${view === "list" ? " task-board--list" : ""}`} aria-busy={tasks.isFetching}>
          {columns.map((status) => <section className="task-column" key={status} aria-labelledby={`column-${status}`}>
            <div className="task-column__heading"><h3 id={`column-${status}`}>{titleCase(status)}</h3><span>{counts[status]}</span></div>
            <div className="task-column__items" role="region" aria-labelledby={`column-${status}`} tabIndex={0}>{tasks.data.results.filter((task) => task.status === status).map((task) => {
              const isTaskArchived = Boolean(task.archived_at);
              const canTransition = !isProjectArchived && !isTaskArchived && (currentRole === "owner" || task.assignees.some((user) => user.id === me.data?.user.id));
              return <article className="task-card" key={task.id}>
              <div className="task-card__meta"><span className="heading-badges"><StatusBadge value={task.priority} />{isTaskArchived && <StatusBadge value="archived" />}</span><span>{task.comment_count} comment{task.comment_count === 1 ? "" : "s"}</span></div>
              <h4><Link to={`/app/projects/${projectId}/tasks/${task.id}/`}>{task.title}</Link></h4>
              <span className="task-card__status"><StatusBadge value={task.status} /></span>
              <p>{task.description || "No description."}</p>
              <div className="avatar-stack" aria-label={task.assignees.length ? `Assigned to ${task.assignees.map((user) => user.display_name).join(", ")}` : "Unassigned"}>{task.assignees.length ? task.assignees.map((user) => <span className="avatar avatar--small" title={user.display_name} key={user.id}>{user.display_name.slice(0, 1).toUpperCase()}</span>) : <span className="muted">Unassigned</span>}</div>
              <small>{formatDate(task.due_at)}</small>
              {canTransition ? <><label className="field field--compact"><span className="sr-only">Move {task.title}</span><select value={blockingTaskId === task.id ? "blocked" : task.status} title="Change task status" onChange={(event) => move(task.id, event.target.value as TaskStatus)} disabled={transition.isPending}>{columns.map((value) => <option key={value} value={value}>{titleCase(value)}</option>)}</select></label>
              {task.status === "blocked" && <Button type="button" variant="quiet" onClick={() => { setError(""); setBlockerDirty(false); setBlockingTaskId(task.id); }}>Edit blocker note</Button>}</> : <span className="task-card__read-only">{isTaskArchived ? "Archived · read-only evidence" : isProjectArchived ? "Project archived · read-only" : "Only an assignee or owner can change status"}</span>}
            </article>;
            })}</div>
          </section>)}
        </div>
      )}
      {blockingTask && !isProjectArchived && <FloatingPanel title={blockingTask.status === "blocked" ? "Edit blocker note" : "Describe the blocker"} busy={transition.isPending} dirty={blockerDirty} onDismiss={() => { setBlockingTaskId(null); setError(""); }}>
        <form className="form-grid" onSubmit={(event) => submitBlocker(blockingTask.id, event)} onChange={() => setBlockerDirty(true)}>
          <Field label="Blocker note" hint="Give teammates enough detail to unblock the work."><textarea name="blocker_note" required minLength={3} maxLength={500} rows={4} defaultValue={blockingTask.blocker_note} autoFocus /></Field>
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="form-actions"><Button type="submit" disabled={transition.isPending}>{transition.isPending ? "Saving…" : "Mark blocked"}</Button></div>
        </form>
      </FloatingPanel>}
    </div>
  );
}
