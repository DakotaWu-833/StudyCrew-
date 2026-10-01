import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet, useLocation, useParams } from "react-router-dom";
import { accountApi, notificationApi, projectApi } from "../api/resources";
import { ErrorState, Loading } from "./UI";

const mainLinks = [
  ["/app/", "Overview", "⌂"],
  ["/app/invitations/", "Invitations", "✉"],
  ["/app/notifications/", "Notifications", "◉"],
  ["/app/profile/", "Profile", "○"],
] as const;

export default function Layout() {
  const me = useQuery({ queryKey: ["me"], queryFn: accountApi.me, staleTime: 60_000 });
  const projects = useQuery({ queryKey: ["projects", "all"], queryFn: projectApi.listAll });
  const unread = useQuery({ queryKey: ["notifications", "unread"], queryFn: () => notificationApi.list(true) });
  const { projectId } = useParams();
  const location = useLocation();
  const selectedId = projectId ?? location.pathname.match(/\/projects\/([^/]+)/)?.[1];
  const selected = projects.data?.results.find((project) => project.id === selectedId);
  const activeProjects = projects.data?.results.filter((project) => !project.archived_at) ?? [];

  if (me.isLoading || projects.isLoading) return <Loading label="Opening your workspace…" />;
  if (me.error || projects.error) return <ErrorState error={me.error ?? projects.error} retry={() => { void me.refetch(); void projects.refetch(); }} />;

  const projectBase = selected ? `/app/projects/${selected.id}` : "";
  return (
    <div className="workspace-shell">
      <aside className="sidebar" aria-label="Workspace navigation">
        <a className="brand" href="/"><span className="brand__mark">S</span><span>StudyCrew</span></a>
        <nav className="nav-list" aria-label="Main">
          {mainLinks.map(([to, label, icon]) => (
            <NavLink key={to} to={to} end={to === "/app/"} aria-label={label} className={({ isActive }) => isActive ? "nav-link nav-link--active" : "nav-link"}>
              <span aria-hidden="true">{icon}</span><span>{label}</span>
              {label === "Notifications" && Boolean(unread.data?.count) && <span className="nav-count" aria-label={`${unread.data?.count} unread`}>{unread.data?.count}</span>}
            </NavLink>
          ))}
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
        <header className="topbar">
          <div>
            <p className="eyebrow">{selected?.archived_at ? `Archived · ${selected.current_user_role}` : selected ? selected.current_user_role : "Workspace"}</p>
            <h1>{selected?.name ?? "Your study workspace"}</h1>
          </div>
          <div className="topbar__actions">
            {me.data?.permissions.site_moderator && <a className="button button--quiet" href="/control/">Site controls</a>}
            <form method="post" action="/account/logout/">
              <input type="hidden" name="csrfmiddlewaretoken" value={document.cookie.match(/(?:^|; )csrftoken=([^;]*)/)?.[1] ?? ""} />
              <button className="button button--quiet" type="submit">Sign out</button>
            </form>
          </div>
        </header>
        {selected && (
          <nav className="project-tabs" aria-label={`${selected.name} sections`}>
            <NavLink to={`${projectBase}/overview/`}>Overview</NavLink>
            <NavLink to={`${projectBase}/tasks/`}>Tasks</NavLink>
            <NavLink to={`${projectBase}/meetings/`}>Meetings</NavLink>
            <NavLink to={`${projectBase}/contributions/`}>Contributions</NavLink>
          </nav>
        )}
        <main id="workspace-main-content" className="page" tabIndex={-1}><Outlet /></main>
      </div>
    </div>
  );
}
