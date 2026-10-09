import ListPagination from "../components/ListPagination";
import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { campusApi, type AcademicTerm, type SearchResults } from "../api/campus";
import { projectApi } from "../api/resources";
import { errorMessage } from "../api/client";
import { formatDate } from "../app/format";
import { Button, ConfirmAction, EmptyState, ErrorState, Field, Loading, Panel, StatusBadge } from "../components/UI";
import "../campus.css";

export default function CampusPage() {
  const client = useQueryClient();
  const overview = useQuery({ queryKey: ["campus"], queryFn: campusApi.overview });
  const projects = useQuery({ queryKey: ["projects", "all"], queryFn: projectApi.listAll });
  const [due, setDue] = useState("open");
  const [todoQuery, setTodoQuery] = useState("");
  const [todoPage, setTodoPage] = useState(1);
  const todos = useQuery({ queryKey: ["campus-todos", due, todoQuery, todoPage], queryFn: () => campusApi.todos(due, todoQuery, todoPage) });
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [copying, setCopying] = useState<AcademicTerm | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [results, setResults] = useState<SearchResults | null>(null);
  const [joinCode, setJoinCode] = useState(() => new URLSearchParams(window.location.search).get("join") ?? "");
  const mutate = useMutation({
    mutationFn: ({ path, data }: { path: string; data: unknown }) => campusApi.action(path, data),
    onSuccess: async () => { setError(""); setMessage("Saved."); setCopying(null); await Promise.all([client.invalidateQueries({ queryKey: ["campus"] }), client.invalidateQueries({ queryKey: ["projects"] }), client.invalidateQueries({ queryKey: ["campus-todos"] })]); },
    onError: (e) => setError(errorMessage(e)),
  });
  const find = useMutation({ mutationFn: ({q, page}: {q: string; page: number}) => campusApi.search(q, page), onSuccess: (data) => { setError(""); setResults(data); }, onError: (e) => setError(errorMessage(e)) });
  const submit = (event: FormEvent<HTMLFormElement>, path: string, build: (data: FormData) => unknown) => {
    event.preventDefault(); setMessage(""); setError(""); mutate.mutate({ path, data: build(new FormData(event.currentTarget)) });
  };
  if (overview.isLoading || projects.isLoading) return <Loading label="Loading your academic workspace…" />;
  if (overview.error || projects.error) return <ErrorState error={overview.error ?? projects.error} retry={() => { void overview.refetch(); void projects.refetch(); }} />;
  const owned = projects.data?.results.filter((project) => project.current_user_role === "owner") ?? [];
  return <div className="page-stack campus-page">
    <div className="page-heading"><div><p className="eyebrow">University work</p><h2>My study planner</h2><p>Organise your own courses and terms, and see responsibilities across your private project teams.</p></div></div>
    {error && <p className="notice notice--error" role="alert">{error}</p>}{message && <p className="notice" role="status">{message}</p>}
    <Panel><h3>My tasks</h3><div className="inline-form"><Field label="Show"><select value={due} onChange={(e) => { setDue(e.target.value); setTodoPage(1); }}><option value="open">Open tasks</option><option value="today">Due today</option><option value="week">Due in the next seven days</option><option value="overdue">Overdue tasks</option><option value="all">All assigned tasks</option></select></Field><Field label="Filter my tasks"><input value={todoQuery} onChange={(e) => { setTodoQuery(e.target.value); setTodoPage(1); }} type="search" /></Field></div>
      {todos.isLoading ? <Loading size="compact" /> : todos.error ? <ErrorState error={todos.error} retry={() => void todos.refetch()} /> : todos.data?.results.length ? <div className="compact-list">{todos.data.results.map((task) => <Link className="compact-row" key={task.id} to={`/app/projects/${task.project}/tasks/${task.id}/`}><span><strong>{task.title}</strong><small>{task.project_name} · Internal deadline {formatDate(task.internal_due_at)}{task.official_due_at && ` · Official deadline ${formatDate(task.official_due_at)}`}</small></span><StatusBadge value={task.status} /></Link>)}</div> : <EmptyState title="No tasks match">Tasks assigned to you in current projects appear here.</EmptyState>}
      {todos.data && <div className="row-actions"><Button variant="quiet" disabled={todos.data.page <= 1 || todos.isFetching} onClick={() => setTodoPage(todos.data!.page - 1)}>Previous tasks</Button><span>{todos.data.total} tasks · Page {todos.data.page} of {todos.data.pages}</span><Button variant="quiet" disabled={todos.data.page >= todos.data.pages || todos.isFetching} onClick={() => setTodoPage(todos.data!.page + 1)}>Next tasks</Button></div>}
    </Panel>
    <Panel><h3>Search my workspaces</h3><form className="inline-form" onSubmit={(event) => { event.preventDefault(); const q = String(new FormData(event.currentTarget).get("q")); setSearchQuery(q); find.mutate({q, page: 1}); }}><Field label="Projects, tasks, meetings, notes, discussions and resources"><input name="q" type="search" required maxLength={100} /></Field><Button disabled={find.isPending}>Search</Button></form>
      {results && <div className="compact-list">{results.projects.map((p) => <Link className="compact-row" key={p.id} to={`/app/projects/${p.id}/plan/`}>Project · {p.name}</Link>)}{results.tasks.map((t) => <Link className="compact-row" key={t.id} to={`/app/projects/${t.project}/tasks/${t.id}/`}>Task · {t.title} · {t.project_name}</Link>)}{results.resources.map((r) => <Link className="compact-row" key={r.id} to={`/app/projects/${r.project}/resources/`}>Resource · {r.title} · {r.project_name}</Link>)}{results.meetings?.map(row => <Link className="compact-row" key={row.id} to={`/app/projects/${row.project}/coordination/`}>Meeting · {row.title}</Link>)}{results.minutes?.map(row => <Link className="compact-row" key={row.id} to={`/app/projects/${row.project}/coordination/`}>Minutes · {row.title} · {row.excerpt}</Link>)}{results.comments?.map(row => <Link className="compact-row" key={row.id} to={`/app/projects/${row.project}/tasks/${row.task}/`}>Comment · {row.title} · {row.excerpt}</Link>)}{results.discussions?.map(row => <Link className="compact-row" key={row.id} to={`/app/projects/${row.project}/updates/`}>Discussion · {row.title}</Link>)}{results.replies?.map(row => <Link className="compact-row" key={row.id} to={`/app/projects/${row.project}/updates/`}>Discussion reply · {row.title} · {row.excerpt}</Link>)}{(results.total === 0 || (results.total === undefined && !results.projects.length && !results.tasks.length && !results.resources.length)) && <p>No results in your current memberships.</p>}<ListPagination info={results} page={results.page ?? 1} onChange={page => find.mutate({q: searchQuery, page})} label="Workspace search" /></div>}
    </Panel>
    <div className="card-grid">
      <Panel><h3>Add a term</h3><p className="muted">These are private, self-reported labels. They do not verify enrolment or grant access to classmates.</p><form className="form-grid" onSubmit={(event) => submit(event, "terms/", (data) => ({ university: data.get("university"), year: Number(data.get("year")), name: data.get("name") }))}><Field label="University"><input name="university" required maxLength={120} /></Field><Field label="Year"><input name="year" type="number" min={2000} max={2100} defaultValue={new Date().getFullYear()} required /></Field><Field label="Term name"><input name="name" placeholder="Semester 1" required maxLength={80} /></Field><Button disabled={mutate.isPending}>Add term</Button></form></Panel>
      <Panel><h3>Add a course</h3><form className="form-grid" onSubmit={(event) => submit(event, "courses/", (data) => ({ university: data.get("university"), code: data.get("code"), name: data.get("name") }))}><Field label="University"><input name="university" required maxLength={120} /></Field><Field label="Course code"><input name="code" placeholder="COMP1001" required maxLength={30} /></Field><Field label="Course name"><input name="name" required maxLength={120} /></Field><Button disabled={mutate.isPending}>Add course</Button></form></Panel>
    </div>
    <Panel><h3>My terms and courses</h3>{overview.data?.terms.length ? <div className="compact-list">{overview.data.terms.map((term) => <div className="compact-row" key={term.id}><span><strong>{term.university} · {term.year} · {term.name}</strong><small>{term.archived_at ? "Archived personal term" : "Current term"}</small></span><span className="row-actions"><Button variant="quiet" onClick={() => setCopying(term)}>Copy for a new term</Button>{!term.archived_at && <ConfirmAction triggerLabel="Archive term" triggerVariant="quiet" confirmLabel="Archive my term" message="Archive this personal term? Shared project history remains accessible to current team members." busy={mutate.isPending} onConfirm={() => mutate.mutate({ path: `terms/${term.id}/archive/`, data: {} })} />}</span></div>)}</div> : <p>Add a term to organise your courses.</p>}
      {overview.data?.courses.map((course) => <p key={course.id}>{course.university} · <strong>{course.code}</strong> · {course.name}</p>)}
      {copying && <form className="form-grid" onSubmit={(event) => submit(event, `terms/${copying.id}/copy/`, (data) => ({ year: Number(data.get("year")), name: data.get("name"), projects: data.getAll("projects") }))}><h4>Copy {copying.name}</h4><p>Copy task descriptions, checklists, dependencies, milestones, agreement text and resource links. Choose new dates, members and reviewers in the new workspaces.</p><Field label="New year"><input name="year" type="number" min={2000} max={2100} defaultValue={copying.year + 1} required /></Field><Field label="New term name"><input name="name" required maxLength={80} /></Field><fieldset className="check-list"><legend>Projects you own in this term</legend>{owned.filter((p) => overview.data?.links.some((l) => l.term.id === copying.id && l.project === p.id)).map((p) => <label key={p.id}><input name="projects" value={p.id} type="checkbox" /> {p.name}</label>)}</fieldset><span className="row-actions"><Button disabled={mutate.isPending}>Create new term and selected projects</Button><Button type="button" variant="quiet" onClick={() => setCopying(null)}>Cancel</Button></span></form>}
    </Panel>
    <Panel><h3>Join a private project</h3><p>A join link requests access. The project owner approves each applicant before project content becomes available.</p><form className="inline-form" onSubmit={(event) => { event.preventDefault(); let token = joinCode.trim(); try { token = new URL(token).searchParams.get("join") ?? token; } catch { /* pasted code */ } mutate.mutate({ path: "join/", data: { token } }, { onSuccess: () => { setJoinCode(""); setMessage("Your request was sent to the project owner."); window.history.replaceState({}, "", window.location.pathname); } }); }}><Field label="Join code or full join link"><input value={joinCode} onChange={(e) => setJoinCode(e.target.value)} required maxLength={2048} /></Field><Button disabled={mutate.isPending}>Request to join</Button></form>{overview.data?.join_requests.map((request) => <p key={request.id}>Request from {formatDate(request.created_at)} · <StatusBadge value={request.status} /> {request.project && <Link to={`/app/projects/${request.project}/overview/`}>Open approved project</Link>}</p>)}</Panel>
  </div>;
}
