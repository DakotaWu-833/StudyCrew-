import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import { invitationApi, membershipApi, projectApi } from "../api/resources";
import type { MemberRole } from "../api/types";
import { formatDate, parseOptionalDateTime, toDateTimeLocal } from "../app/format";
import Avatar from "../components/Avatar";
import { Button, ConfirmAction, EmptyState, ErrorState, Field, FloatingPanel, Loading, Panel, StatusBadge } from "../components/UI";

export default function ProjectOverviewPage() {
  const { projectId = "" } = useParams();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [editDirty, setEditDirty] = useState(false);
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => projectApi.get(projectId), enabled: Boolean(projectId) });
  const memberships = useQuery({ queryKey: ["memberships", projectId], queryFn: () => membershipApi.list(projectId), enabled: Boolean(projectId) });
  const invites = useQuery({ queryKey: ["invitations", projectId], queryFn: () => invitationApi.listForProject(projectId), enabled: project.data?.current_user_role === "owner" && !project.data.archived_at });

  const refreshMembers = () => queryClient.invalidateQueries({ queryKey: ["memberships", projectId] });
  const update = useMutation({ mutationFn: (data: { name: string; description: string; due_at: string | null }) => projectApi.update(projectId, data), onSuccess: async () => { await Promise.all([queryClient.invalidateQueries({ queryKey: ["project", projectId] }), queryClient.invalidateQueries({ queryKey: ["projects"] })]); setEditing(false); setError(""); setNotice("Project details saved."); }, onError: (value) => setError(errorMessage(value)) });
  const invite = useMutation({ mutationFn: (email: string) => invitationApi.create(projectId, email), onSuccess: async (created) => { await queryClient.invalidateQueries({ queryKey: ["invitations", projectId] }); setError(""); setNotice(`Invitation email sent to ${created.invited_email}.`); }, onError: (value) => setError(errorMessage(value)) });
  const cancelInvite = useMutation({ mutationFn: invitationApi.cancel, onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ["invitations", projectId] }); setError(""); setNotice("Invitation cancelled."); }, onError: (value) => setError(errorMessage(value)) });
  const role = useMutation({ mutationFn: ({ id, value }: { id: string; value: MemberRole }) => membershipApi.updateRole(id, value), onSuccess: async () => { await refreshMembers(); setError(""); setNotice("Member role updated."); }, onError: (value) => setError(errorMessage(value)) });
  const remove = useMutation({ mutationFn: membershipApi.remove, onSuccess: async () => { await Promise.all([refreshMembers(), queryClient.invalidateQueries({ queryKey: ["project", projectId] }), queryClient.invalidateQueries({ queryKey: ["projects"] }), queryClient.invalidateQueries({ queryKey: ["tasks", projectId] }), queryClient.invalidateQueries({ queryKey: ["task"] })]); setError(""); setNotice("Member removed from the project and cleared from current task assignments."); }, onError: (value) => setError(errorMessage(value)) });
  const transfer = useMutation({ mutationFn: membershipApi.transferOwnership, onSuccess: async () => { await Promise.all([refreshMembers(), queryClient.invalidateQueries({ queryKey: ["project", projectId] }), queryClient.invalidateQueries({ queryKey: ["projects"] })]); setError(""); setNotice("Ownership transferred."); }, onError: (value) => setError(errorMessage(value)) });
  const archive = useMutation({ mutationFn: () => projectApi.archive(projectId), onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ["projects"] }); navigate("/app/"); }, onError: (value) => setError(errorMessage(value)) });

  if (project.isLoading || memberships.isLoading) return <Loading label="Loading project…" />;
  if (project.error || memberships.error) return <ErrorState error={project.error ?? memberships.error} retry={() => { void project.refetch(); void memberships.refetch(); }} />;
  if (!project.data) return null;
  const isOwner = project.data.current_user_role === "owner";
  const isArchived = Boolean(project.data.archived_at);

  const submitEdit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError(""); setNotice("");
    const data = new FormData(event.currentTarget);
    const dueAt = parseOptionalDateTime(String(data.get("due_at")));
    if (dueAt === undefined) { setError("Choose a valid due date and time."); return; }
    update.mutate({ name: String(data.get("name")), description: String(data.get("description")), due_at: dueAt });
  };
  const submitInvite = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError(""); setNotice("");
    const form = event.currentTarget;
    invite.mutate(String(new FormData(form).get("email")), { onSuccess: () => form.reset() });
  };

  return (
    <div className="page-stack">
      {(notice || error) && <p className={error ? "notice notice--error" : "notice"} role={error ? "alert" : "status"}>{error || notice}</p>}
      {isArchived && <p className="notice" role="status">This project is archived. Its retained workspace is read-only.</p>}
      <div className="stats-grid">
        <div className="stat"><strong>{project.data.member_count}</strong><span>{isArchived ? "Retained members" : "Active members"}</span></div>
        <div className="stat"><strong>{project.data.current_user_role}</strong><span>Your role</span></div>
        <div className="stat"><strong>{formatDate(project.data.due_at, false)}</strong><span>Project due date</span></div>
      </div>

      <Panel labelledBy="project-details-heading">
        <div className="section-heading"><div><h2 id="project-details-heading">Project details</h2><p>{project.data.description || "No description yet."}</p></div>{isOwner && !isArchived && <Button variant="secondary" onClick={() => { setEditDirty(false); setError(""); setEditing(true); }}>Edit</Button>}</div>
      </Panel>
      {editing && <FloatingPanel title="Edit project details" busy={update.isPending} dirty={editDirty} onDismiss={() => setEditing(false)}>
        <form className="form-grid" onSubmit={submitEdit} onChange={() => setEditDirty(true)}>
          <Field label="Project name"><input name="name" required minLength={3} maxLength={100} defaultValue={project.data.name} autoFocus /></Field>
          <Field label="Due date and time"><input name="due_at" type="datetime-local" defaultValue={toDateTimeLocal(project.data.due_at)} /></Field>
          <Field label="Description"><textarea name="description" maxLength={2000} rows={4} defaultValue={project.data.description} /></Field>
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="form-actions"><Button type="submit" disabled={update.isPending}>{update.isPending ? "Saving…" : "Save details"}</Button></div>
        </form>
      </FloatingPanel>}

      <Panel labelledBy="members-heading">
        <div className="section-heading"><h2 id="members-heading">Team</h2><span>{memberships.data?.count} active</span></div>
        <div className="data-list">
          {memberships.data?.results.map((member) => (
            <div className="data-row" key={member.id}>
              <Avatar name={member.user.display_name} imageUrl={member.user.avatar_image_url || member.user.avatar_url} version={member.user.avatar_image_url ? member.user.avatar_version : undefined} />
              <span className="data-row__main"><strong>{member.user.display_name}</strong><StatusBadge value={member.role} /></span>
              {isOwner && !isArchived && member.role !== "owner" && (
                <span className="row-actions">
                  <label className="sr-only" htmlFor={`role-${member.id}`}>Role for {member.user.display_name}</label>
                  <select id={`role-${member.id}`} value={member.role} disabled={role.isPending || remove.isPending || transfer.isPending} onChange={(event) => role.mutate({ id: member.id, value: event.target.value as MemberRole })}>
                    <option value="member">Member</option><option value="facilitator">Facilitator</option>
                  </select>
                  <ConfirmAction triggerLabel="Make owner" triggerVariant="quiet" confirmLabel="Transfer ownership" message={`Transfer project ownership to ${member.user.display_name}? Your role will become facilitator.`} busy={role.isPending || remove.isPending || transfer.isPending} onConfirm={() => transfer.mutate(member.id)} />
                  <ConfirmAction triggerLabel="Remove" confirmLabel="Remove member" message={`Remove ${member.user.display_name} from this project and all current task assignments?`} busy={role.isPending || remove.isPending || transfer.isPending} onConfirm={() => remove.mutate(member.id)} />
                </span>
              )}
            </div>
          ))}
        </div>
      </Panel>

      {isOwner && !isArchived && (
        <Panel labelledBy="invite-heading">
          <h2 id="invite-heading">Invite a teammate</h2>
          <form className="inline-form" onSubmit={submitInvite}><Field label="Email address"><input name="email" type="email" required autoComplete="email" /></Field><Button type="submit" disabled={invite.isPending}>{invite.isPending ? "Sending…" : "Send invitation"}</Button></form>
          {invites.isLoading ? <Loading label="Loading invitations…" /> : invites.error ? <ErrorState error={invites.error} retry={() => void invites.refetch()} /> : invites.data?.count ? <div className="compact-list">{invites.data.results.map((item) => <div className="compact-row" key={item.id}><span><strong>{item.invited_email}</strong><small>Expires {formatDate(item.expires_at)}</small></span><span className="row-actions"><StatusBadge value={item.status} />{item.status === "pending" && <ConfirmAction triggerLabel="Cancel" triggerVariant="quiet" confirmLabel="Cancel invitation" message={`Cancel the invitation for ${item.invited_email}?`} busy={cancelInvite.isPending} onConfirm={() => cancelInvite.mutate(item.id)} />}</span></div>)}</div> : <EmptyState title="No invitations">New pending invitations will appear here.</EmptyState>}
        </Panel>
      )}

      {isOwner && !isArchived && <Panel className="danger-zone" labelledBy="archive-heading"><h2 id="archive-heading">Archive project</h2><p>Archiving removes the project from every member's active workspace. Evidence remains recorded.</p><ConfirmAction triggerLabel="Archive project" confirmLabel="Archive for everyone" message="Archive this project for every member? The retained workspace will become read-only." busy={archive.isPending} onConfirm={() => archive.mutate()} /></Panel>}
    </div>
  );
}
