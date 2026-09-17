import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { errorMessage } from "../api/client";
import { notificationApi } from "../api/resources";
import type { Notification } from "../api/types";
import { formatDate, titleCase } from "../app/format";
import { Button, EmptyState, ErrorState, Loading, Panel } from "../components/UI";

function safeTarget(notification: Notification) {
  return notification.target_url.startsWith("/app/") ? notification.target_url : "/app/notifications/";
}

export default function NotificationsPage() {
  const client = useQueryClient();
  const navigate = useNavigate();
  const notifications = useQuery({ queryKey: ["notifications", "all"], queryFn: () => notificationApi.list(false) });
  const markRead = useMutation({ mutationFn: notificationApi.markRead, onSuccess: async () => { await Promise.all([client.invalidateQueries({ queryKey: ["notifications", "all"] }), client.invalidateQueries({ queryKey: ["notifications", "unread"] })]); } });
  if (notifications.isLoading) return <Loading label="Loading notifications…" />;
  if (notifications.error) return <ErrorState error={notifications.error} retry={() => void notifications.refetch()} />;
  return <div className="page-stack"><div className="page-heading"><div><p className="eyebrow">Updates</p><h2>Notifications</h2><p>Assignment, meeting and invitation changes addressed to you.</p></div></div>
    {markRead.error && <p className="notice notice--error" role="alert">{errorMessage(markRead.error)}</p>}
    {!notifications.data?.count ? <EmptyState title="You are up to date">New project activity addressed to you will appear here.</EmptyState> : <Panel><div className="notification-list">{notifications.data.results.map((item) => <article key={item.id} className={item.is_read ? "notification notification--read" : "notification"}>
      <span className="notification__mark" aria-hidden="true" /><div className="notification__body"><strong>{titleCase(item.notification_type)}</strong><span>{item.project_name}</span><time dateTime={item.created_at}>{formatDate(item.created_at)}</time></div><span className="row-actions"><Link className="button button--quiet" to={safeTarget(item)} onClick={(event) => { if (!item.is_read) { event.preventDefault(); markRead.mutate(item.id, { onSuccess: () => navigate(safeTarget(item)) }); } }}>Open</Link>{!item.is_read && <Button variant="quiet" onClick={() => markRead.mutate(item.id)} disabled={markRead.isPending}>Mark read</Button>}</span>
    </article>)}</div></Panel>}
  </div>;
}
