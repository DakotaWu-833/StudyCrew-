import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { errorMessage } from "../api/client";
import { notificationApi } from "../api/resources";
import { operationsApi } from "../api/operations";
import type { Notification } from "../api/types";
import { formatDate, titleCase } from "../app/format";
import ListPagination from "../components/ListPagination";
import { Button, EmptyState, ErrorState, Loading, Panel } from "../components/UI";

function safeTarget(notification: Notification) {
  return notification.target_url.startsWith("/app/") ? notification.target_url : "/app/notifications/";
}

export default function NotificationsPage() {
  const [page, setPage] = useState(1);
  const client = useQueryClient();
  const navigate = useNavigate();
  const notifications = useQuery({ queryKey: ["notifications", "all"], queryFn: () => notificationApi.list(false) });
  const alerts = useQuery({ queryKey: page === 1 ? ["scheduled-alerts"] : ["scheduled-alerts", page], queryFn: () => operationsApi.alerts(page) });
  const refresh = async () => { await Promise.all([client.invalidateQueries({ queryKey: ["notifications"] }), client.invalidateQueries({ queryKey: ["scheduled-alerts"] })]); };
  const readAll = useMutation({ mutationFn: operationsApi.readAll, onSuccess: refresh });
  const readAlert = useMutation({ mutationFn: operationsApi.readAlert, onSuccess: refresh });
  const markRead = useMutation({ mutationFn: notificationApi.markRead, onSuccess: async () => { await Promise.all([client.invalidateQueries({ queryKey: ["notifications", "all"] }), client.invalidateQueries({ queryKey: ["notifications", "unread"] })]); } });
  if (notifications.isLoading) return <Loading label="Loading notifications…" />;
  if (notifications.error) return <ErrorState error={notifications.error} retry={() => void notifications.refetch()} />;
  return <div className="page-stack"><div className="page-heading"><div><p className="eyebrow">Updates</p><h2>Notifications</h2><p>Assignment, meeting, invitation and deadline updates addressed to you.</p></div><div className="row-actions"><Link className="button button--quiet" to="/app/notification-settings/">Notification settings</Link><Button variant="secondary" onClick={() => readAll.mutate()} disabled={readAll.isPending}>Mark all read</Button></div></div>
    {(readAlert.error || readAll.error) && <ErrorState error={readAlert.error || readAll.error} />}
    {alerts.error && <ErrorState error={alerts.error} retry={() => void alerts.refetch()} />}
    {!!alerts.data?.results.length && <Panel><h3>Deadline reminders</h3><div className="notification-list">{alerts.data.results.map(item => <article key={item.id} className={item.read_at ? "notification notification--read" : "notification"}><span className="notification__mark" aria-hidden="true" /><div className="notification__body"><strong>{item.title}</strong><span>{item.body}</span><time dateTime={item.created_at}>{formatDate(item.created_at)}</time></div><span className="row-actions"><Link className="button button--quiet" to={item.target_url.startsWith("/app/") ? item.target_url : "/app/notifications/"} onClick={() => { if (!item.read_at) readAlert.mutate(item.id); }}>Open</Link>{!item.read_at && <Button variant="quiet" disabled={readAlert.isPending} onClick={() => readAlert.mutate(item.id)}>Mark read</Button>}</span></article>)}</div><ListPagination info={alerts.data} page={page} onChange={setPage} label="Deadline reminders" /></Panel>}
    {markRead.error && <p className="notice notice--error" role="alert">{errorMessage(markRead.error)}</p>}
    {!notifications.data?.count ? !alerts.data?.results.length && <EmptyState title="You are up to date">New project activity addressed to you will appear here.</EmptyState> : <Panel><h3>Project activity</h3><div className="notification-list">{notifications.data.results.map((item) => <article key={item.id} className={item.is_read ? "notification notification--read" : "notification"}>
      <span className="notification__mark" aria-hidden="true" /><div className="notification__body"><strong>{titleCase(item.notification_type)}</strong><span>{item.project_name}</span><time dateTime={item.created_at}>{formatDate(item.created_at)}</time></div><span className="row-actions"><Link className="button button--quiet" to={safeTarget(item)} onClick={(event) => { if (!item.is_read) { event.preventDefault(); markRead.mutate(item.id, { onSuccess: () => navigate(safeTarget(item)) }); } }}>Open</Link>{!item.is_read && <Button variant="quiet" onClick={() => markRead.mutate(item.id)} disabled={markRead.isPending}>Mark read</Button>}</span>
    </article>)}</div></Panel>}
  </div>;
}
