import DraftForm from "../components/DraftForm";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { discussionsApi, type ProjectPost } from "../api/discussions";
import { membershipApi, projectApi } from "../api/resources";
import { Button, ConfirmAction, ErrorState, Field, Loading, Panel, StatusBadge } from "../components/UI";
import ListPagination from "../components/ListPagination";

function PostCard({ post, mentions }: { post: ProjectPost; mentions: { id: string; display_name: string }[] }) {
  const cache = useQueryClient(), [editing, setEditing] = useState(false), [message, setMessage] = useState(""), [replyPage, setReplyPage] = useState(1);
  const replyList = useQuery({ queryKey: ["post-replies", post.id, replyPage], queryFn: () => discussionsApi.replies(post.id, replyPage), enabled: replyPage > 1 });
  const change = useMutation({ mutationFn: ({ kind, data }: { kind: "update" | "reply" | "remove" | "report"; data: Record<string, unknown> }) => {
    if (kind === "update") return discussionsApi.update(post.id, { ...data, expected_updated_at: post.updated_at });
    if (kind === "reply") return discussionsApi.reply(post.id, data);
    if (kind === "remove") return discussionsApi.remove(post.id, data.reply_id as string | undefined);
    return discussionsApi.report(post.id, String(data.reason), data.reply_id as string | undefined);
  }, onSuccess: () => { void cache.invalidateQueries({ queryKey: ["project-posts", post.project] }); void cache.invalidateQueries({ queryKey: ["post-replies", post.id] }); } });
  const readonly = post.read_only || !!post.removed_at;
  const mentionField = <Field label="Notify these teammates (optional)"><select name="mention_ids" multiple>{mentions.map(user => <option key={user.id} value={user.id}>@{user.display_name}</option>)}</select></Field>;
  return <article className="launch-ticket"><div className="launch-row"><h3>{post.title}</h3><StatusBadge value={post.kind} />{post.pinned && <span>Pinned decision</span>}</div><p className="muted">{post.author.display_name} · {new Date(post.created_at).toLocaleString()}</p><p className="launch-preserve">{post.body}</p>
    {!readonly && <div className="row-actions">{post.can_edit && <><Button variant="quiet" onClick={() => setEditing(!editing)}>Edit</Button><ConfirmAction triggerLabel="Remove discussion" confirmLabel="Remove" message="Remove this discussion from the team view? Its report and audit records are retained." busy={change.isPending} onConfirm={() => change.mutate({ kind: "remove", data: {} })} /></>}{post.manager && <Button variant="quiet" disabled={change.isPending} onClick={() => change.mutate({ kind: "update", data: { pinned: !post.pinned } })}>{post.pinned ? "Unpin decision" : "Pin decision"}</Button>}</div>}
    {editing && !readonly && <form className="launch-form" onSubmit={event => { event.preventDefault(); const data = new FormData(event.currentTarget); change.mutate({ kind: "update", data: { title: data.get("title"), body: data.get("body"), mention_ids: data.getAll("mention_ids") } }, { onSuccess: () => setEditing(false) }); }}><Field label="Discussion title"><input name="title" defaultValue={post.title} minLength={3} maxLength={120} required /></Field><Field label="Discussion content"><textarea name="body" defaultValue={post.body} maxLength={6000} rows={5} required /></Field>{mentionField}<Button disabled={change.isPending}>Save edit</Button></form>}
    {(replyPage === 1 ? post.replies : replyList.data?.results ?? []).map(reply => <blockquote key={reply.id}><strong>{reply.author.display_name}</strong><p className="launch-preserve">{reply.removed_at || post.removed_at ? "Reply removed" : reply.body}</p>{!readonly && !reply.removed_at && <>{reply.can_remove && <ConfirmAction triggerLabel="Remove reply" triggerVariant="quiet" confirmLabel="Remove reply" message="Remove this reply from the discussion?" busy={change.isPending} onConfirm={() => change.mutate({ kind: "remove", data: { reply_id: reply.id } })} />}<details><summary>Report reply</summary><form className="launch-form" onSubmit={event => { event.preventDefault(); const form = event.currentTarget; change.mutate({ kind: "report", data: { reason: new FormData(form).get("reason"), reply_id: reply.id } }, { onSuccess: () => { form.reset(); setMessage("Report saved. Track its status in Help and feedback."); } }); }}><Field label="Why are you reporting this reply?"><textarea name="reason" minLength={5} maxLength={500} required /></Field><Button disabled={change.isPending}>Submit reply report</Button></form></details></>}</blockquote>)}
    {replyList.error && <ErrorState error={replyList.error} />}
    {replyList.isFetching && replyPage > 1 && <Loading />}
    <ListPagination info={replyPage === 1 ? post.reply_pagination : replyList.data} page={replyPage} onChange={setReplyPage} label="Discussion replies" />
    {!readonly && <><form className="launch-form" onSubmit={event => { event.preventDefault(); const form = event.currentTarget, data = new FormData(form); change.mutate({ kind: "reply", data: { body: data.get("body"), mention_ids: data.getAll("mention_ids") } }, { onSuccess: () => form.reset() }); }}><Field label="Reply to this discussion"><textarea name="body" maxLength={2000} rows={2} required /></Field>{mentionField}<Button variant="secondary" disabled={change.isPending}>Post reply</Button></form><details><summary>Report discussion</summary><form className="launch-form" onSubmit={event => { event.preventDefault(); const form = event.currentTarget; change.mutate({ kind: "report", data: { reason: new FormData(form).get("reason") } }, { onSuccess: () => { form.reset(); setMessage("Report saved. Track its status in Help and feedback."); } }); }}><Field label="Why are you reporting this discussion?"><textarea name="reason" minLength={5} maxLength={500} required /></Field><Button disabled={change.isPending}>Submit report</Button></form></details></>}
    {message && <p role="status">{message}</p>}{change.error && <ErrorState error={change.error} />}
  </article>;
}

export default function ProjectUpdatesPage() {
  const { projectId = "" } = useParams(); const cache = useQueryClient(), [page, setPage] = useState(1);
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => projectApi.get(projectId) });
  const members = useQuery({ queryKey: ["memberships", projectId], queryFn: () => membershipApi.list(projectId) });
  const posts = useQuery({ queryKey: ["project-posts", projectId, page], queryFn: () => discussionsApi.list(projectId, page) });
  const create = useMutation({ mutationFn: (data: unknown) => discussionsApi.create(projectId, data), onSuccess: () => { setPage(1); void cache.invalidateQueries({ queryKey: ["project-posts", projectId] }); } });
  const manager = ["owner", "facilitator"].includes(project.data?.current_user_role ?? "");
  const people = members.data?.results.map(row => row.user) ?? [];
  if (project.isLoading || posts.isLoading) return <Loading />;
  if (project.error || posts.error || members.error) return <ErrorState error={project.error || posts.error || members.error} retry={() => { void posts.refetch(); void project.refetch(); void members.refetch(); }} />;
  return <div className="page-stack"><div className="page-heading"><div><h2>Team discussions and decisions</h2><p>Keep important announcements, questions and decisions together. Mentions notify only the teammates you select.</p></div></div>
    {!project.data?.archived_at && <Panel><h3>Start a discussion</h3><DraftForm scope={`discussion:${projectId}:new`} fields={["title", "body"]} className="launch-form" onSubmit={event => { event.preventDefault(); const form = event.currentTarget, data = new FormData(form); create.mutate({ title: data.get("title"), body: data.get("body"), kind: data.get("kind") ?? "discussion", pinned: data.has("pinned"), mention_ids: data.getAll("mention_ids") }, { onSuccess: () => form.reset() }); }}><Field label="Title"><input name="title" minLength={3} maxLength={120} required /></Field><Field label="Message"><textarea name="body" required maxLength={6000} rows={5} /></Field>{manager && <><Field label="Post type"><select name="kind"><option value="discussion">Discussion</option><option value="announcement">Team announcement</option></select></Field><label><input name="pinned" type="checkbox" /> Pin this decision</label></>}<Field label="Mention teammates"><select name="mention_ids" multiple>{people.map(user => <option key={user.id} value={user.id}>@{user.display_name}</option>)}</select></Field><Button disabled={create.isPending}>Post to team</Button>{create.error && <ErrorState error={create.error} />}</DraftForm></Panel>}
    <Panel><h3>Recent discussions</h3>{posts.data?.results.length ? posts.data.results.map(post => <PostCard key={post.id} post={post} mentions={people} />) : <p>No discussions yet. Start with your team's next decision.</p>}<ListPagination info={posts.data} page={page} onChange={setPage} label="Team discussions" /></Panel>
  </div>;
}
