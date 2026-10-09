import { useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { campusApi, type Resource } from "../api/campus";
import { errorMessage } from "../api/client";
import { Button, ConfirmAction, EmptyState, ErrorState, Field, Loading, Panel } from "../components/UI";
import "../campus.css";

export default function ResourcesPage() {
  const { projectId = "" } = useParams();
  const client = useQueryClient();
  const [query, setQuery] = useState("");
  const [tag, setTag] = useState("");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Resource | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const resources = useQuery({ queryKey: ["resources", projectId, query, tag, page], queryFn: () => campusApi.resources(projectId, query, tag, page), enabled: Boolean(projectId) });
  const plan = useQuery({ queryKey: ["project-plan", projectId], queryFn: () => campusApi.plan(projectId), enabled: Boolean(projectId) });
  const change = useMutation({ mutationFn: ({ path, data, method }: { path: string; data: unknown; method: string }) => campusApi.projectAction(projectId, path, data, method), onSuccess: async () => { setError(""); setMessage("Resource links updated."); setEditing(null); await client.invalidateQueries({ queryKey: ["resources", projectId] }); }, onError: (e) => setError(errorMessage(e)) });
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    change.mutate({ path: editing ? `resources/${editing.id}/` : "resources/", method: editing ? "PATCH" : "POST", data: { title: data.get("title"), url: data.get("url"), description: data.get("description"), tags: String(data.get("tags") ?? "").split(",").map((t) => t.trim()).filter(Boolean), pinned: data.get("pinned") === "on" } });
  };
  if (plan.isLoading || resources.isLoading) return <Loading label="Loading project resources…" />;
  if (plan.error || resources.error) return <ErrorState error={plan.error ?? resources.error} retry={() => { void plan.refetch(); void resources.refetch(); }} />;
  const readOnly = Boolean(plan.data?.project.archived_at);
  return <div className="page-stack campus-page"><div className="page-heading"><div><p className="eyebrow">Shared materials</p><h2>Resource links</h2><p>Keep assignment briefs, documents, repositories and final deliverables in your private team workspace.</p></div></div>
    {error && <p className="notice notice--error" role="alert">{error}</p>}{message && <p className="notice" role="status">{message}</p>}
    <Panel><div className="inline-form"><Field label="Search titles, descriptions and links"><input type="search" value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} maxLength={100} /></Field><Field label="Filter by tag"><input value={tag} onChange={(event) => { setTag(event.target.value); setPage(1); }} maxLength={30} /></Field></div></Panel>
    {!readOnly && <Panel><h3>{editing ? "Edit resource link" : "Add resource link"}</h3><form key={editing?.id ?? "new"} className="form-grid" onSubmit={submit}><Field label="Title"><input name="title" required maxLength={150} defaultValue={editing?.title ?? ""} /></Field><Field label="Public HTTP or HTTPS URL"><input name="url" type="url" required maxLength={2048} defaultValue={editing?.url ?? ""} placeholder="https://..." /></Field><Field label="Description"><textarea name="description" maxLength={1000} defaultValue={editing?.description ?? ""} /></Field><Field label="Tags separated by commas"><input name="tags" defaultValue={editing?.tags.join(", ") ?? ""} placeholder="brief, research, final" /></Field><label><input name="pinned" type="checkbox" defaultChecked={editing?.pinned ?? false} /> Pin this link</label><div className="form-actions"><Button disabled={change.isPending}>{editing ? "Save link" : "Add link"}</Button>{editing && <Button type="button" variant="quiet" onClick={() => setEditing(null)}>Cancel edit</Button>}</div></form><p className="muted">Access to linked documents is managed by their provider. Check sharing permissions before adding a link.</p></Panel>}
    {resources.data?.results.length ? resources.data.results.map((resource) => <Panel key={resource.id}><div className="section-heading"><h3>{resource.pinned && "★ "}{resource.title}</h3>{!readOnly && resource.can_edit && <span className="row-actions"><Button variant="quiet" onClick={() => setEditing(resource)}>Edit</Button><Button variant="quiet" disabled={change.isPending} onClick={() => change.mutate({ path: `resources/${resource.id}/`, method: "PATCH", data: { pinned: !resource.pinned } })}>{resource.pinned ? "Unpin" : "Pin"}</Button><ConfirmAction triggerLabel="Remove" triggerVariant="quiet" confirmLabel="Remove link" message={`Remove ${resource.title} from this workspace?`} busy={change.isPending} onConfirm={() => change.mutate({ path: `resources/${resource.id}/`, method: "DELETE", data: {} })} /></span>}</div><p>{resource.description}</p><a href={resource.url} target="_blank" rel="noopener noreferrer">Open resource ↗</a><p className="muted">{resource.tags.join(" · ")} · Added by {resource.added_by.display_name}</p></Panel>) : <EmptyState title="No resource links match">Add a useful link or clear the search filters.</EmptyState>}
    {resources.data && <div className="row-actions"><Button variant="quiet" disabled={resources.data.page <= 1 || resources.isFetching} onClick={() => setPage(resources.data!.page - 1)}>Previous resources</Button><span>{resources.data.total} links · Page {resources.data.page} of {resources.data.pages}</span><Button variant="quiet" disabled={resources.data.page >= resources.data.pages || resources.isFetching} onClick={() => setPage(resources.data!.page + 1)}>Next resources</Button></div>}
  </div>;
}
