import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { invitationApi, projectApi } from "../api/resources";
import { campusApi } from "../api/campus";
import { errorMessage } from "../api/client";
import { formatDate, parseOptionalDateTime } from "../app/format";
import { Button, EmptyState, ErrorState, Field, FloatingPanel, Loading, StatusBadge } from "../components/UI";

export default function DashboardPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const projects = useQuery({ queryKey: ["projects", "all"], queryFn: projectApi.listAll });
  const invitations = useQuery({ queryKey: ["invitations", "mine"], queryFn: invitationApi.listMine });
  const todos = useQuery({ queryKey: ["personal-todos", "dashboard"], queryFn: () => campusApi.todos() });
  const [showCreate, setShowCreate] = useState(false);
  const [formError, setFormError] = useState("");
  const createProject = useMutation({
    mutationFn: projectApi.create,
    onSuccess: async (project) => {
      await queryClient.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/app/projects/${project.id}/overview/`);
    },
    onError: (error) => setFormError(errorMessage(error)),
  });

  if (projects.isLoading) return <Loading label="Loading projects…" />;
  if (projects.error) return <ErrorState error={projects.error} retry={() => void projects.refetch()} />;
  const activeProjects = projects.data?.results.filter((project) => !project.archived_at) ?? [];
  const archivedProjects = projects.data?.results.filter((project) => Boolean(project.archived_at)) ?? [];

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError("");
    const data = new FormData(event.currentTarget);
    const dueAt = parseOptionalDateTime(String(data.get("due_at") ?? ""));
    if (dueAt === undefined) { setFormError("Choose a valid due date and time."); return; }
    createProject.mutate({
      name: String(data.get("name") ?? ""),
      description: String(data.get("description") ?? ""),
      due_at: dueAt,
    });
  };

  return (
    <div className="page-stack">
      <div className="page-heading">
        <div><p className="eyebrow">Overview</p><h2>Keep the group moving</h2><p>Projects, invitations and the next pieces of work in one place.</p></div>
        <Button onClick={() => setShowCreate(true)} aria-expanded={showCreate}>New project</Button>
      </div>

      {!activeProjects.length && <section className="panel" aria-labelledby="getting-started"><h3 id="getting-started">Set up your study group</h3><ol><li><Link to="/app/campus/">Add your course and semester</Link>.</li><li>Create a project and invite your team.</li><li>Open Project plan to choose a template, agree responsibilities and set deadlines.</li><li>Use Calendar and Meeting tools to find a time and record decisions.</li></ol><Link to="/app/security/">Set a recovery email before you rely on the account</Link></section>}
      <section aria-labelledby="personal-work"><div className="section-heading"><h2 id="personal-work">My next tasks</h2><Link to="/app/campus/">All personal tasks</Link></div>{todos.isLoading ? <Loading label="Checking your tasks…" /> : todos.error ? <ErrorState error={todos.error} retry={() => void todos.refetch()} /> : todos.data?.results.length ? <div className="compact-list">{todos.data.results.slice(0, 5).map(task => <Link className="compact-row" key={task.id} to={`/app/projects/${task.project}/tasks/${task.id}/`}><span><strong>{task.title}</strong><small>{task.project_name}</small></span><span>Due {formatDate(task.internal_due_at)}</span></Link>)}</div> : <p className="muted">You have no open assigned tasks.</p>}</section>

      {showCreate && (
        <FloatingPanel title="Create a project" onDismiss={() => setShowCreate(false)}>
          <form className="form-grid" onSubmit={submit}>
            <Field label="Project name"><input name="name" minLength={3} maxLength={100} required autoFocus /></Field>
            <Field label="Due date and time" hint="Optional; shown in your local time."><input name="due_at" type="datetime-local" /></Field>
            <Field label="Description"><textarea name="description" maxLength={2000} rows={3} /></Field>
            {formError && <p className="form-error" role="alert">{formError}</p>}
            <div className="form-actions"><Button type="submit" disabled={createProject.isPending}>{createProject.isPending ? "Creating…" : "Create project"}</Button><Button type="button" variant="quiet" disabled={createProject.isPending} onClick={() => setShowCreate(false)}>Cancel</Button></div>
          </form>
        </FloatingPanel>
      )}

      <section aria-labelledby="projects-heading">
        <div className="section-heading"><h2 id="projects-heading">Active projects</h2><span>{activeProjects.length} total</span></div>
        {!activeProjects.length ? (
          <EmptyState title="Start with one shared project">Create a project, invite your group, then divide the work into visible tasks.</EmptyState>
        ) : (
          <div className="card-grid">
            {activeProjects.map((project) => (
              <Link className="project-card" to={`/app/projects/${project.id}/overview/`} key={project.id}>
                <div className="project-card__top"><StatusBadge value={project.current_user_role} /><span>{project.member_count} member{project.member_count === 1 ? "" : "s"}</span></div>
                <h3>{project.name}</h3>
                <p>{project.description || "No project description yet."}</p>
                <span className="project-card__due">Due {formatDate(project.due_at)}</span>
              </Link>
            ))}
          </div>
        )}
      </section>

      {archivedProjects.length > 0 && <section aria-labelledby="archived-projects-heading">
        <div className="section-heading"><h2 id="archived-projects-heading">Archived projects</h2><span>{archivedProjects.length} retained</span></div>
        <div className="card-grid">
          {archivedProjects.map((project) => (
            <Link className="project-card" to={`/app/projects/${project.id}/overview/`} key={project.id}>
              <div className="project-card__top"><StatusBadge value="archived" /><span>Read-only history</span></div>
              <h3>{project.name}</h3>
              <p>{project.description || "No project description was recorded."}</p>
              <span className="project-card__due">Archived {formatDate(project.archived_at)}</span>
            </Link>
          ))}
        </div>
      </section>}

      <section aria-labelledby="invitations-heading">
        <div className="section-heading"><h2 id="invitations-heading">Pending invitations</h2><Link to="/app/invitations/">View all</Link></div>
        {invitations.isLoading ? <Loading label="Checking invitations…" /> : invitations.error ? <ErrorState error={invitations.error} /> : invitations.data?.count ? (
          <div className="compact-list">
            {invitations.data.results.slice(0, 3).map((invitation) => (
              <Link to={`/app/invitations/${invitation.id}/`} key={invitation.id} className="compact-row"><span><strong>{invitation.project_name}</strong><small>Invited by {invitation.invited_by.display_name}</small></span><span>Respond</span></Link>
            ))}
          </div>
        ) : <p className="muted">You have no invitations waiting.</p>}
      </section>
    </div>
  );
}
