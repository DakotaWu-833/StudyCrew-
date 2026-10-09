import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { operationsApi, type SupportTicket } from "../api/operations";
import ListPagination from "../components/ListPagination";
import { Button, EmptyState, ErrorState, Field, Loading, Panel, StatusBadge } from "../components/UI";

export function TicketCard({ ticket, admin = false }: { ticket: SupportTicket; admin?: boolean }) {
  const cache = useQueryClient();
  const reply = useMutation({ mutationFn: (body: string) => operationsApi.reply(ticket.id, body), onSuccess: () => { void cache.invalidateQueries({ queryKey: [admin ? "admin-support" : "support"] }); } });
  const resolve = useMutation({ mutationFn: (value: { status: string; resolution: string }) => operationsApi.updateTicket(ticket.id, value), onSuccess: () => { void cache.invalidateQueries({ queryKey: ["admin-support"] }); } });
  return <article className="launch-ticket"><div className="launch-row"><h3>{ticket.subject}</h3><StatusBadge value={ticket.status} /></div><small>{ticket.category} · {new Date(ticket.created_at).toLocaleString()}{admin && ticket.requester_name ? ` · ${ticket.requester_name}` : ""}</small><p className="launch-preserve">{ticket.description}</p>
    {ticket.replies.map(row => <blockquote key={row.id}><strong>{row.author_name}</strong><p className="launch-preserve">{row.body}</p><small>{new Date(row.created_at).toLocaleString()}</small></blockquote>)}
    {ticket.resolution && <p><strong>Resolution:</strong> {ticket.resolution}</p>}
    <form className="launch-form" onSubmit={event => { event.preventDefault(); const form = event.currentTarget; reply.mutate(String(new FormData(form).get("body")), { onSuccess: () => form.reset() }); }}><Field label="Reply"><textarea name="body" required maxLength={2000} rows={2} /></Field><Button variant="secondary" disabled={reply.isPending}>Send reply</Button></form>{reply.error && <ErrorState error={reply.error} />}
    {admin && <form className="launch-form" onSubmit={event => { event.preventDefault(); const form = new FormData(event.currentTarget); resolve.mutate({ status: String(form.get("status")), resolution: String(form.get("resolution")) }); }}><Field label="Case status"><select name="status" defaultValue={ticket.status}><option value="open">Open</option><option value="in_progress">In progress</option><option value="awaiting_user">Awaiting user</option><option value="resolved">Resolved</option></select></Field><Field label="Resolution or next step"><textarea name="resolution" maxLength={2000} defaultValue={ticket.resolution} /></Field><Button disabled={resolve.isPending}>Update case</Button>{resolve.error && <ErrorState error={resolve.error} />}</form>}
  </article>;
}

export default function SupportPage() {
  const [page, setPage] = useState(1);
  const cache = useQueryClient(); const [message, setMessage] = useState("");
  const tickets = useQuery({ queryKey: page === 1 ? ["support"] : ["support", page], queryFn: () => operationsApi.tickets(page) });
  const create = useMutation({ mutationFn: operationsApi.createTicket, onSuccess: () => { setMessage("Your request has been saved. Replies and progress will appear here."); void cache.invalidateQueries({ queryKey: ["support"] }); } });
  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const form = event.currentTarget; const data = new FormData(form); create.mutate({ category: String(data.get("category")), subject: String(data.get("subject")), description: String(data.get("description")) }, { onSuccess: () => form.reset() }); }
  return <div className="page-stack"><div className="page-heading"><div><h2>Help and feedback</h2><p>Track an issue, ask a question, or request a review.</p></div><a className="button button--quiet" href="/status/">Service status</a></div>
    <Panel><h3>New request</h3><p className="muted">Include useful details. Keep passwords, verification codes and private assessment materials out of support requests.</p><form className="launch-form" onSubmit={submit}><Field label="Category"><select name="category"><option value="help">Help</option><option value="bug">Bug report</option><option value="appeal">Moderation appeal</option><option value="privacy">Privacy request</option><option value="feedback">Feedback</option></select></Field><Field label="Subject"><input name="subject" required maxLength={160} /></Field><Field label="Details"><textarea name="description" required maxLength={4000} rows={4} /></Field><Button disabled={create.isPending}>Send request</Button>{message && <p role="status">{message}</p>}{create.error && <ErrorState error={create.error} />}</form></Panel>
    <Panel><h3>Your requests</h3>{tickets.isLoading ? <Loading size="compact" label="Loading support requests…" /> : tickets.error ? <ErrorState error={tickets.error} size="compact" retry={() => void tickets.refetch()} /> : <>{tickets.data?.results.length ? tickets.data.results.map(ticket => <TicketCard key={ticket.id} ticket={ticket} />) : <EmptyState title="No requests yet">Questions and feedback are welcome.</EmptyState>}<ListPagination info={tickets.data} page={page} onChange={setPage} label="Support requests" /></>}</Panel>
    <Panel><h3>Useful pages</h3><p><a href="/help/">Getting started</a> · <a href="/privacy/">Privacy and retention</a> · <a href="/app/security/">Account recovery and devices</a></p></Panel></div>;
}
