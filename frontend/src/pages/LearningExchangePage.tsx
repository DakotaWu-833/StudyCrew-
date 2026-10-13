import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { learningExchangeApi as api, type LearningPreview } from "../api/learningExchange";
import { errorMessage } from "../api/client";
import { formatDate } from "../app/format";
import { Button, ErrorState, Field, Loading, Panel } from "../components/UI";
import "./learning-exchange.css";
import "../extensions.css";

export default function LearningExchangePage() {
  const { projectId = "" } = useParams();
  const client = useQueryClient();
  const [page, setPage] = useState(1);
  const [preview, setPreview] = useState<LearningPreview | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [message, setMessage] = useState("");
  const overview = useQuery({ queryKey: ["learning-exchange", projectId, page], queryFn: () => api.overview(projectId, page), enabled: Boolean(projectId) });
  const upload = useMutation({ mutationFn: (data: FormData) => api.preview(projectId, data), onSuccess: (data) => { setPreview(data); setConfirmed(false); setMessage(""); } });
  const importFile = useMutation({
    mutationFn: (id: string) => api.confirm(projectId, id),
    onSuccess: async (result) => {
      setMessage(result.replayed ? "This file was already imported. No duplicate tasks were created." : `Imported ${result.batch.imported_count} assignments. Skipped ${result.batch.skipped_count} existing source IDs.`);
      setPreview(null); setConfirmed(false);
      await Promise.all([client.invalidateQueries({ queryKey: ["learning-exchange", projectId] }), client.invalidateQueries({ queryKey: ["project-plan", projectId] }), client.invalidateQueries({ queryKey: ["tasks", projectId] }), client.invalidateQueries({ queryKey: ["campus-todos"] }), client.invalidateQueries({ queryKey: ["calendar"] })]);
    },
  });
  function prepare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPreview(null); setConfirmed(false); setMessage(""); importFile.reset();
    const form = new FormData(event.currentTarget);
    const file = form.get("file");
    if (!(file instanceof File) || !file.size) return;
    upload.mutate(form);
  }
  if (overview.isPending) return <Loading label="Loading assignment exchange" />;
  if (overview.error || !overview.data) return <ErrorState error={overview.error} retry={() => void overview.refetch()} />;
  const data = overview.data;
  const busy = upload.isPending || importFile.isPending;
  return <div className="page-stack learning-exchange">
    <div><h1>Assignment file exchange</h1><p className="muted">{data.project.name} · Import a file you obtained yourself, preview every row, then create real project tasks.</p></div>
    <Panel><h2>Manual exchange with your learning platform</h2>
      <p>This local CSV adapter does not sign in to a university or fetch its data. Canvas and Moodle options recognise only the example headers listed below; other exports need conversion to the sample format.</p>
      <p><a href={api.sampleUrl} download>Download generic sample CSV</a> · <a href={api.exportUrl(projectId)} download>Export current task deadlines and status</a> · <Link to={`/app/projects/${projectId}/plan`}>Open assignment plan</Link></p>
      <p className="muted">Exports escape spreadsheet formulas. The current-task export includes official and internal deadlines; each batch export retains the confirmed import snapshot, including skipped rows.</p>
    </Panel>
    {message && <p className="notice" role="status">{message}</p>}
    {data.project.can_import ? <Panel><h2>1. Upload and validate</h2>
      <form className="form-grid" onSubmit={prepare} onChange={() => { setPreview(null); setConfirmed(false); }}>
        <fieldset className="form-grid" disabled={busy}><legend>Private project import</legend>
          <Field label="UTF-8 CSV file (256 KiB, 100 assignments maximum)"><input name="file" type="file" accept=".csv,text/csv" required /></Field>
          <div className="card-grid"><Field label="Column format"><select name="source" defaultValue="generic"><option value="generic">Generic sample</option><option value="canvas">Canvas-style fixture headers</option><option value="moodle">Moodle-style fixture headers</option></select></Field><Field label="Source or course label"><input name="source_namespace" defaultValue="manual" required maxLength={80} placeholder="COMP1010-2026-S2" /></Field></div>
          <Field label="Timezone for deadlines without an offset"><input name="timezone_name" key={data.timezone_name} defaultValue={data.timezone_name} required maxLength={64} placeholder="Australia/Sydney" /></Field>
          <p className="muted">Use ISO dates with a time, preferably an explicit UTC offset. Repeated or missing daylight-saving times are rejected. Imports set the initial internal deadline to the official deadline. Stable source IDs prevent later files from overwriting an assignment.</p>
          <details><summary>Supported columns</summary><p>Generic: source_id, title, description, official_due_at, priority.<br />Canvas-style fixture: Assignment ID, Assignment Name, Description, Due Date, Priority.<br />Moodle-style fixture: ID number, Item name, Description, Due date, Priority.</p><p>Priority: low, medium, high or urgent. Empty deadlines are allowed. Unknown columns are reported and ignored. Without source_id, an ID is derived from the content, so changed content can create another task.</p></details>
          <Button disabled={busy}>Preview file</Button>
        </fieldset>
      </form>
      {upload.error && <p role="alert">{errorMessage(upload.error)}</p>}
    </Panel> : <p className="notice">{data.project.archived_at ? "This project is archived. Its imports are read-only." : "Only a project owner or facilitator can import assignments."}</p>}
    {preview && <Panel><h2>2. Review every assignment</h2>
      <p>{preview.create_count} to create · {preview.skip_count} existing source IDs to skip · timezone {preview.timezone_name}</p>
      {preview.ignored_columns.length > 0 && <p className="notice">Ignored columns: {preview.ignored_columns.join(", ")}</p>}
      {!preview.valid && <p role="alert">The whole file must be valid. Correct the errors and preview it again; no tasks have been created.</p>}
      <div className="learning-table-wrap"><table><thead><tr><th>CSV row</th><th>Assignment / source ID</th><th>Official deadline (UTC)</th><th>Result</th></tr></thead><tbody>{preview.rows.map(row => <tr key={row.row}><td>{row.row}</td><td><strong>{row.title}</strong><div>{row.source_id}</div>{row.description && <details><summary>Description</summary><p>{row.description}</p></details>}<span>{row.priority}</span></td><td>{row.official_due_at ?? "No deadline"}</td><td>{row.errors.length ? <ul>{row.errors.map(error => <li key={error}>{error}</li>)}</ul> : row.action === "skip" ? "Skip existing assignment; never overwrite" : "Create task"}</td></tr>)}</tbody></table></div>
      {preview.valid && preview.preview_id && data.project.can_import && <div className="form-grid"><p className="muted">Preview expires {formatDate(preview.expires_at)}. Changed duplicates or expired previews require another upload.</p><label><input type="checkbox" checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)} /> I reviewed every row and confirm this import into {data.project.name}.</label><Button disabled={!confirmed || busy} onClick={() => importFile.mutate(preview.preview_id!)}>Confirm import</Button></div>}
      {importFile.error && <p role="alert">{errorMessage(importFile.error)}</p>}
    </Panel>}
    <Panel><h2>Import history</h2>
      {!data.batches.length && <p>No confirmed imports yet.</p>}
      {data.batches.map(batch => <article className="learning-batch" key={batch.id}><div><strong>{batch.source_namespace}</strong> · {batch.source}<p>{formatDate(batch.created_at)} · {batch.imported_count} created · {batch.skipped_count} skipped</p></div><a href={api.exportUrl(projectId, batch.id)} download>Export batch snapshot</a></article>)}
      {data.pages > 1 && <div className="inline-form"><Button variant="secondary" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</Button><span>Page {data.page} of {data.pages}</span><Button variant="secondary" disabled={page === data.pages} onClick={() => setPage(page + 1)}>Next</Button></div>}
    </Panel>
  </div>;
}
