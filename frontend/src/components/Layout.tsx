import { Suspense } from "react";
import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { accountApi, notificationApi, projectApi } from "../api/resources";
import { operationsApi } from "../api/operations";
import { ErrorState, Loading } from "./UI";
import BrowserReadiness from "./BrowserReadiness";

const mainLinks = [
  ["/app/", "Overview", "⌂"],
  ["/app/campus/", "My studies", "▣"],
  ["/app/find-team/", "Find a team", "♧"],
  ["/app/calendar/", "Calendar", "▦"],
  ["/app/invitations/", "Invitations", "✉"],
  ["/app/notifications/", "Notifications", "◉"],
  ["/app/profile/", "Profile", "○"],
  ["/app/notification-settings/", "Notification settings", "⚙"],
  ["/app/security/", "Security & privacy", "◇"],
  ["/app/support/", "Help & feedback", "?"],
] as const;

const projectSections = [
  ["overview", "Overview", "Overview"],
  ["plan", "Project plan", "Plan"],
  ["tasks", "Tasks", "Tasks"],
  ["workload", "Workload", "Workload"],
  ["meetings", "Meetings", "Meetings"],
  ["coordination", "Meeting tools", "Tools"],
  ["resources", "Resources", "Resources"],
  ["files", "Files", "Files"],
  ["learning", "Assignment import", "Import"],
  ["updates", "Discussions", "Discussions"],
  ["chat", "Chat", "Chat"],
  ["contributions", "Contributions", "Contributions"],
  ["evidence", "Evidence & claims", "Evidence"],
] as const;

export default function Layout() {
  const me = useQuery({ queryKey: ["me"], queryFn: accountApi.me, staleTime: 60_000 });
  const projects = useQuery({ queryKey: ["projects", "all"], queryFn: projectApi.listAll });
  const unread = useQuery({ queryKey: ["notifications", "unread"], queryFn: () => notificationApi.list(true), refetchInterval: 30000 });
  const alerts = useQuery({ queryKey: ["scheduled-alerts"], queryFn: () => operationsApi.alerts(), refetchInterval: 30000 });
  const notices = useQuery({ queryKey: ["service-notices"], queryFn: operationsApi.notices, refetchInterval: 60000 });
  const unreadCount = (unread.data?.count ?? 0) + (alerts.data?.count ?? 0);
  const { projectId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const selectedId = projectId ?? location.pathname.match(/\/projects\/([^/]+)/)?.[1];
  const selected = projects.data?.results.find((project) => project.id === selectedId);
  const activeProjects = projects.data?.results.filter((project) => !project.archived_at) ?? [];

  if (me.isLoading || projects.isLoading) return <Loading label="Opening your workspace…" />;
  if (me.error || projects.error) return <ErrorState error={me.error ?? projects.error} retry={() => { void me.refetch(); void projects.refetch(); }} />;

  const projectBase = selected ? `/app/projects/${selected.id}` : "";
  const currentSection = projectSections.find(([section]) => {
    const sectionPath = `${projectBase}/${section}`;
    return location.pathname === sectionPath || location.pathname.startsWith(`${sectionPath}/`);
  })?.[0] ?? "overview";
  return (
    <div className="workspace-shell">
      <aside className="sidebar" aria-label="Workspace navigation">
        <a className="brand" href="/"><span className="brand__mark">S</span><span>StudyCrew</span></a>
        <nav className="nav-list" aria-label="Main">
          {mainLinks.map(([to, label, icon]) => (
            <NavLink key={to} to={to} end={to === "/app/"} aria-label={label} className={({ isActive }) => isActive ? "nav-link nav-link--active" : "nav-link"}>
              <span aria-hidden="true">{icon}</span><span>{label}</span>
              {label === "Notifications" && Boolean(unreadCount) && <span className="nav-count" aria-label={`${unreadCount} unread`}>{unreadCount}</span>}
            </NavLink>
          ))}
          {me.data?.permissions.site_moderator && <NavLink to="/app/operations/" className={({ isActive }) => isActive ? "nav-link nav-link--active" : "nav-link"}><span aria-hidden="true">⚙</span><span>Service operations</span></NavLink>}
          <NavLink to="/app/offline/" aria-label="Offline tasks" className={({ isActive }) => isActive ? "nav-link nav-link--active" : "nav-link"}>
            <span aria-hidden="true">⇄</span><span>Offline tasks</span>
          </NavLink>
        </nav>
        <div className="sidebar__projects">
          <p className="sidebar__eyebrow">Projects</p>
          {activeProjects.map((project) => (
            <NavLink key={project.id} to={`/app/projects/${project.id}/overview/`} className={({ isActive }) => isActive ? "project-link project-link--active" : "project-link"}>
              <span className="project-link__dot" aria-hidden="true" />
              <span>{project.name}</span>
            </NavLink>
          ))}
          {!activeProjects.length && <span className="sidebar__empty">No active projects</span>}
        </div>
        <div className="sidebar__account">
          <span className="avatar" aria-hidden="true">{me.data?.profile.avatar_image_url || me.data?.profile.avatar_url
            ? <img src={me.data.profile.avatar_image_url
              ? `${me.data.profile.avatar_image_url}?v=${encodeURIComponent(me.data.profile.updated_at)}`
              : me.data.profile.avatar_url} alt="" />
            : me.data?.user.display_name.slice(0, 1).toUpperCase()}</span>
          <span><strong>{me.data?.user.display_name}</strong><small>{me.data?.email}</small></span>
        </div>
      </aside>
      <div className="workspace-main">
        <BrowserReadiness userId={me.data?.user.id} />
        <header className="topbar">
          <div>
            <p className="eyebrow">{selected?.archived_at ? `Archived · ${selected.current_user_role}` : selected ? selected.current_user_role : "Workspace"}</p>
            <h1>{selected?.name ?? "Your study workspace"}</h1>
          </div>
          <div className="topbar__actions">
            {me.data?.permissions.site_moderator && <NavLink className="button button--quiet" to="/app/operations/">Service operations</NavLink>}
            <form method="post" action="/account/logout/">
              <input type="hidden" name="csrfmiddlewaretoken" value={document.cookie.match(/(?:^|; )csrftoken=([^;]*)/)?.[1] ?? ""} />
              <button className="button button--quiet" type="submit">Sign out</button>
            </form>
          </div>
        </header>
        {selected && (
          <div className="project-navigation">
            <nav className="project-tabs" aria-label={`${selected.name} sections`}>
              <div className="project-tabs__links">
                {projectSections.map(([section, label, compactLabel]) => (
                  <NavLink key={section} to={`${projectBase}/${section}/`} aria-label={label} title={label}>{compactLabel}</NavLink>
                ))}
              </div>
              <label className="project-tabs__picker">
                <span>Section</span>
                <select aria-label="Project section" value={currentSection} onChange={event => navigate(`${projectBase}/${event.target.value}/`)}>
                  {projectSections.map(([section, label]) => <option key={section} value={section}>{label}</option>)}
                </select>
              </label>
            </nav>
          </div>
        )}
        <main id="workspace-main-content" className="page" tabIndex={-1}>{notices.data?.results.map(notice => <div className="notice" role="status" key={notice.id}><strong>{notice.title}</strong><p>{notice.body}</p></div>)}<Suspense fallback={<Loading label="Opening page…" />}><Outlet /></Suspense></main>
      </div>
    </div>
  );
}
