import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import { invitationApi } from "../api/resources";
import { formatDate } from "../app/format";
import { Button, ConfirmAction, EmptyState, ErrorState, Loading, Panel, StatusBadge } from "../components/UI";

export default function InvitationsPage() {
  const { invitationId } = useParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const invitations = useQuery({ queryKey: ["invitations", "mine"], queryFn: invitationApi.listMine });
  const accept = useMutation({ mutationFn: invitationApi.accept, onSuccess: async (project) => { await Promise.all([client.invalidateQueries({ queryKey: ["invitations"] }), client.invalidateQueries({ queryKey: ["projects"] })]); navigate(`/app/projects/${project.id}/overview/`); } });
  const decline = useMutation({ mutationFn: invitationApi.decline, onSuccess: async () => { await client.invalidateQueries({ queryKey: ["invitations"] }); navigate("/app/invitations/"); } });
  if (invitations.isLoading) return <Loading label="Loading invitations…" />;
  if (invitations.error) return <ErrorState error={invitations.error} retry={() => void invitations.refetch()} />;
  const items = invitations.data?.results ?? [];
  const mutationError = accept.error ?? decline.error;
  return <div className="page-stack"><div className="page-heading"><div><p className="eyebrow">Join a team</p><h2>Invitations</h2><p>Only invitations sent to your verified sign-in email appear here.</p></div></div>
    {mutationError && <p className="notice notice--error" role="alert">{errorMessage(mutationError)}</p>}
    {!items.length ? <EmptyState title="Nothing waiting">You have no pending project invitations.</EmptyState> : <div className="card-grid">{items.map((invitation) => <Panel key={invitation.id} className={invitation.id === invitationId ? "invitation-card invitation-card--focus" : "invitation-card"}>
      <div className="heading-badges"><StatusBadge value={invitation.status} /><span>Expires {formatDate(invitation.expires_at)}</span></div><h3>{invitation.project_name}</h3><p>{invitation.invited_by.display_name} invited {invitation.invited_email} to collaborate.</p><div className="form-actions"><Button onClick={() => accept.mutate(invitation.id)} disabled={accept.isPending || decline.isPending}>Accept invitation</Button><ConfirmAction triggerLabel="Decline" triggerVariant="secondary" confirmLabel="Decline invitation" message={`Decline the invitation to ${invitation.project_name}?`} busy={accept.isPending || decline.isPending} onConfirm={() => decline.mutate(invitation.id)} /></div>
    </Panel>)}</div>}
  </div>;
}
