import { useEffect, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { privateFilesApi, type ProjectDocument, type FileVersion, type FileDiff } from "../api/privateFiles";
import { projectApi } from "../api/resources";
import { errorMessage } from "../api/client";
import { Button, ConfirmAction, EmptyState, ErrorState, Field, Loading, Panel } from "../components/UI";
import "../extensions.css";
import "./private-files.css";
import FilePreview from "./FilePreview";

export function fileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
const tagsFrom = (value: FormDataEntryValue | null) => String(value ?? "").split(",").map(tag => tag.trim()).filter(Boolean);

export default function ProjectFilesPage() {
  const { projectId = "" } = useParams();
  const cache = useQueryClient();
  const [q, setQ] = useState("");
  const [folder, setFolder] = useState("");
  const [tag, setTag] = useState("");
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState("");
  const [showTrash, setShowTrash] = useState(false);
  const [trashPage, setTrashPage] = useState(1);
  const [preview, setPreview] = useState<{ documentId: string; version: FileVersion } | null>(null);
  const [diff, setDiff] = useState<FileDiff | null>(null);
  const [diffError, setDiffError] = useState("");
  const [editing, setEditing] = useState<ProjectDocument | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { setSelectedId(""); setEditing(null); setPreview(null); setDiff(null); setDiffError(""); setShowTrash(false); setMessage(""); setError(""); setPage(1); setTrashPage(1); }, [projectId]);
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => projectApi.get(projectId), enabled: Boolean(projectId) });
  const files = useQuery({ queryKey: ["private-files", projectId, q, folder, tag, page], queryFn: () => privateFilesApi.list(projectId, q, folder, tag, page), enabled: Boolean(projectId) });
  const detail = useQuery({ queryKey: ["private-file", projectId, selectedId], queryFn: () => privateFilesApi.detail(projectId, selectedId), enabled: Boolean(selectedId) });
  const trash = useQuery({ queryKey: ["private-files-trash", projectId, q, trashPage], queryFn: () => privateFilesApi.trash(projectId, q, trashPage), enabled: Boolean(projectId) && showTrash });
  const change = useMutation({
    mutationFn: (action: () => Promise<unknown>) => action(),
    onSuccess: async () => { setError(""); setMessage("Project files updated."); setEditing(null); setDiff(null); await Promise.all([cache.invalidateQueries({ queryKey: ["private-files", projectId] }), cache.invalidateQueries({ queryKey: ["private-file", projectId] }), cache.invalidateQueries({ queryKey: ["private-files-trash", projectId] })]); },
    onError: (failure) => setError(errorMessage(failure)),
  });
  const compare = useMutation({ mutationFn: ({ id, from, to }: { id: string; from: string; to: string }) => privateFilesApi.compare(projectId, id, from, to),
    onSuccess: (result, values) => { if (values.id === selectedId) { setDiff(result); setDiffError(""); } },
    onError: (failure, values) => { if (values.id === selectedId) { setDiff(null); setDiffError(errorMessage(failure)); } } });
  const upload = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const form = event.currentTarget; const data = new FormData(form);
    data.set("tags", JSON.stringify(tagsFrom(data.get("tags"))));
    change.mutate(() => privateFilesApi.upload(projectId, data), { onSuccess: () => form.reset() });
  };
  const update = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (!editing) return; const data = new FormData(event.currentTarget);
    change.mutate(() => privateFilesApi.update(projectId, editing.id, { title: data.get("title"), folder: data.get("folder"), tags: tagsFrom(data.get("tags")), ...(canManage ? { pinned: data.get("pinned") === "on" } : {}), expected_revision: editing.revision }));
  };
  const version = (event: FormEvent<HTMLFormElement>, doc: ProjectDocument) => {
    event.preventDefault(); const form = event.currentTarget; const data = new FormData(form);
    data.set("expected_revision", String(doc.revision));
    change.mutate(() => privateFilesApi.version(projectId, doc.id, data), { onSuccess: () => form.reset() });
  };
  if (project.isLoading || files.isLoading) return <Loading label="Loading private project files…" />;
  if (project.error || files.error) return <ErrorState error={project.error ?? files.error} retry={() => { void project.refetch(); void files.refetch(); }} />;
  const readOnly = Boolean(project.data?.archived_at);
  const canManage = ["owner", "facilitator"].includes(project.data?.current_user_role ?? "");
  const selected = detail.data;
  const textVersions = selected?.versions.filter(item => item.preview_kind === "text") ?? [];
  return <div className="page-stack extension-page"><div className="page-heading"><div><p className="eyebrow">Team materials</p><h2>Private project files</h2><p>Upload briefs and deliverables, organise them by folder, and keep previous versions. Only current project members can download files.</p></div></div>
    {error && <p className="notice notice--error" role="alert">{error}</p>}{message && <p className="notice" role="status">{message}</p>}
    {readOnly && <p className="notice">This project is archived. Its files are read-only.</p>}
    <Panel><div className="row-actions"><Button type="button" variant={showTrash ? "quiet" : "secondary"} onClick={() => { setShowTrash(false); setSelectedId(""); setPreview(null); setDiff(null); }}>Active files</Button><Button type="button" variant={showTrash ? "secondary" : "quiet"} onClick={() => { setShowTrash(true); setSelectedId(""); setPreview(null); setEditing(null); setDiff(null); }}>Recycle bin</Button></div><div className="inline-form"><Field label="Search files"><input type="search" value={q} maxLength={100} onChange={e => { setQ(e.target.value); setPage(1); setTrashPage(1); }} /></Field>{!showTrash && <><Field label="Folder filter"><input value={folder} maxLength={80} onChange={e => { setFolder(e.target.value); setPage(1); }} /></Field><Field label="File tag filter"><input value={tag} maxLength={30} onChange={e => { setTag(e.target.value); setPage(1); }} /></Field></>}</div>
      {files.data && <p className="muted">{fileSize(files.data.usage.bytes)} of {fileSize(files.data.usage.limit)} used, including retained versions · Up to {fileSize(files.data.usage.file_limit)} per file.</p>}
    </Panel>
    {!showTrash && !readOnly && files.data && <Panel><h3>{editing ? "Edit file details" : "Upload a file"}</h3><form key={editing?.id ?? "upload"} className="form-grid" onSubmit={editing ? update : upload}>
      <Field label="File title"><input name="title" required maxLength={150} defaultValue={editing?.title ?? ""} /></Field><Field label="Folder"><input name="folder" maxLength={80} defaultValue={editing?.folder ?? ""} placeholder="e.g. Research" /></Field><Field label="File tags separated by commas"><input name="tags" defaultValue={editing?.tags.join(", ") ?? ""} /></Field>
      {!editing && <Field label="Choose file"><input name="file" type="file" required accept={files.data.allowed_extensions.map(ext => ext.startsWith(".") ? ext : `.${ext}`).join(",")} /></Field>}
      {canManage && <label><input type="checkbox" name="pinned" defaultChecked={editing?.pinned ?? false} /> Pin this file</label>}<div className="form-actions"><Button disabled={change.isPending}>{editing ? "Save file details" : "Upload file"}</Button>{editing && <Button type="button" variant="quiet" onClick={() => setEditing(null)}>Cancel edit</Button>}</div>
    </form><p className="muted">Supported: {files.data.allowed_extensions.join(", ")}. {files.data.scan_required ? "Files must pass the configured malware scanner." : "Malware scanning is not enabled in this local preview. Download materials from teammates you trust."}</p></Panel>}
    {!showTrash && (files.data?.results.length ? files.data.results.map(doc => <Panel key={doc.id}><div className="section-heading"><div><h3>{doc.pinned && "★ "}{doc.title}</h3><p className="muted">{doc.folder || "Unfiled"} · {doc.tags.join(" · ")} · Added by {doc.author.display_name}</p></div><div className="row-actions"><a className="button button--secondary" href={doc.latest.download_url}>Download {doc.latest.filename}</a>{doc.latest.preview_kind && <Button type="button" variant="quiet" onClick={() => setPreview({ documentId: doc.id, version: doc.latest })}>Preview</Button>}<Button type="button" variant="quiet" onClick={() => { setSelectedId(selectedId === doc.id ? "" : doc.id); setDiff(null); setDiffError(""); }}>{selectedId === doc.id ? "Hide versions" : "Versions"}</Button>{doc.can_edit && !readOnly && <><Button type="button" variant="quiet" onClick={() => setEditing(doc)}>Edit details</Button><ConfirmAction triggerLabel="Remove file" confirmLabel="Remove this file" message={`Remove ${doc.title}? It will immediately disappear from member downloads. The author or a project manager can restore it from the recycle bin within 30 days.`} busy={change.isPending} onConfirm={() => change.mutate(() => privateFilesApi.remove(projectId, doc.id, doc.revision), { onSuccess: () => { if (selectedId === doc.id) setSelectedId(""); if (preview?.documentId === doc.id) setPreview(null); } })} /></>}</div></div><p>Version {doc.latest.number} · {fileSize(doc.latest.size)} · {doc.latest.scan_status === "clean" ? "Scanner passed" : "Not malware scanned"}</p></Panel>) : <EmptyState title="No files match">Upload a file or clear the filters.</EmptyState>)}
    {showTrash && <><p className="notice">Removed files cannot be downloaded or previewed. Their author or a project manager can restore them within 30 days. Retained files still count toward project storage.</p>{trash.isLoading && <Loading label="Loading recycle bin…" />}{trash.error && <ErrorState error={trash.error} retry={() => void trash.refetch()} />}{trash.data && (trash.data.results.length ? trash.data.results.map(doc => <Panel key={doc.id}><div className="section-heading"><div><h3>{doc.title}</h3><p className="muted">{doc.folder || "Unfiled"} · Added by {doc.author.display_name}</p><p>Removed {new Date(doc.removed_at).toLocaleString()} · Restoration ends {new Date(doc.purge_after).toLocaleString()}</p></div>{doc.can_restore && !readOnly ? <Button type="button" disabled={change.isPending} onClick={() => change.mutate(() => privateFilesApi.restore(projectId, doc.id, doc.revision))}>Restore file</Button> : <p className="muted">Restoration is unavailable for your current permissions or the retention period.</p>}</div></Panel>) : <EmptyState title="Recycle bin is empty">There are no recoverable files matching this search.</EmptyState>)}{trash.data && <div className="row-actions"><Button type="button" variant="quiet" disabled={trashPage <= 1 || trash.isFetching} onClick={() => setTrashPage(trashPage - 1)}>Previous removed files</Button><span>{trash.data.count} removed files · Page {trash.data.page} of {trash.data.pages}</span><Button type="button" variant="quiet" disabled={trashPage >= trash.data.pages || trash.isFetching} onClick={() => setTrashPage(trashPage + 1)}>Next removed files</Button></div>}</>}
    {preview && !showTrash && <FilePreview key={`${preview.documentId}:${preview.version.id}`} projectId={projectId} documentId={preview.documentId} version={preview.version} onClose={() => setPreview(null)} />}
    {selectedId && !showTrash && <Panel><h3>Version history</h3>{detail.isLoading && <Loading label="Loading versions…" />}{detail.error && <ErrorState error={detail.error} retry={() => void detail.refetch()} />}{selected && <><p>{selected.title}</p><ul className="file-versions">{selected.versions.map(item => <li key={item.id}><div className="row-actions"><a href={item.download_url}>Version {item.number}: {item.filename}</a>{item.preview_kind && <Button type="button" variant="quiet" onClick={() => setPreview({ documentId: selected.id, version: item })}>Preview version {item.number}</Button>}</div><span>{fileSize(item.size)} · {new Date(item.created_at).toLocaleString()} · {item.scan_status === "clean" ? "Scanner passed" : "Not malware scanned"}</span><details><summary>Integrity checksum</summary><code>{item.sha256}</code></details></li>)}</ul>
      {textVersions.length >= 2 && <><h4>Compare text versions</h4><form key={selected.id + selected.revision} className="inline-form" onSubmit={event => { event.preventDefault(); const data = new FormData(event.currentTarget); compare.mutate({ id: selected.id, from: String(data.get("from_version")), to: String(data.get("to_version")) }); }}><Field label="Earlier version"><select name="from_version" defaultValue={textVersions[1]?.id}>{textVersions.map(item => <option key={item.id} value={item.id}>Version {item.number}: {item.filename}</option>)}</select></Field><Field label="Later version"><select name="to_version" defaultValue={textVersions[0]?.id}>{textVersions.map(item => <option key={item.id} value={item.id}>Version {item.number}: {item.filename}</option>)}</select></Field><Button disabled={compare.isPending}>Compare versions</Button></form><p className="muted">Text and CSV only · Up to 256 KB and 2,000 lines per version. Added lines start with +; removed lines start with −.</p>{diffError && <p role="alert" className="notice notice--error">{diffError}</p>}{diff && <>{diff.identical && <p role="status">The text in these versions is identical.</p>}{diff.line_ending_changed && <p className="notice">The line endings or final newline changed.</p>}<div className="private-file-diff" aria-label="Text version comparison">{diff.lines.map((line, index) => <div key={index}><pre className={`diff-${line.kind}`}>{line.text}</pre>{line.no_final_newline && <p className="diff-newline">No newline at end of file</p>}</div>)}</div>{diff.truncated && <p className="notice">Comparison output is truncated. Download both versions for the complete changes.</p>}</>}</>}
      {selected.can_edit && !readOnly && <form className="inline-form" onSubmit={event => version(event, selected)}><Field label="New file version"><input name="file" type="file" required accept={files.data?.allowed_extensions.map(ext => ext.startsWith(".") ? ext : `.${ext}`).join(",")} /></Field><Button disabled={change.isPending}>Upload new version</Button></form>}</>}</Panel>}
    {!showTrash && files.data && <div className="row-actions"><Button type="button" variant="quiet" disabled={page <= 1 || files.isFetching} onClick={() => setPage(page - 1)}>Previous files</Button><span>{files.data.count} files · Page {files.data.page} of {files.data.pages}</span><Button type="button" variant="quiet" disabled={page >= files.data.pages || files.isFetching} onClick={() => setPage(page + 1)}>Next files</Button></div>}
  </div>;
}
