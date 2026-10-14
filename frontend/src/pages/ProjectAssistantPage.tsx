import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { assistantApi, type AssistantCreatedTask, type AssistantDraft, type AssistantResult, type AssistantSettings, type AssistantSource, type AssistantTaskRequest } from "../api/assistant";
import { APIError } from "../api/client";
import { Button, ConfirmAction, EmptyState, ErrorState, Field, Loading, Panel } from "../components/UI";
import "./project-assistant.css";

const toolLabels: Record<string, string> = {
  search_sources: "Searched project sources",
  search_project_sources: "Searched project sources",
  list_tasks: "Checked project tasks",
  list_project_tasks: "Checked project tasks",
  propose_task_drafts: "Prepared task drafts",
  propose_tasks: "Prepared task drafts",
};
const citationLabel = /^[A-Z][A-Z0-9_-]{0,31}$/;
const sourceTarget = (citation: string) => `assistant-source-${citation}`;
function sourceHref(value: string): string | null {
  if (!value) return null;
  try {
    const url = new URL(value, window.location.origin);
    if (!["http:", "https:"].includes(url.protocol) || url.origin !== window.location.origin) return null;
    return `${url.pathname}${url.search}${url.hash}`;
  } catch { return null; }
}

function Citation({ citation, sources }: { citation: string; sources: AssistantSource[] }) {
  return citationLabel.test(citation) && sources.some(source => source.citation === citation)
    ? <a href={`#${sourceTarget(citation)}`} aria-label={`Read source ${citation}`}>[{citation}]</a>
    : <span>[{citation}]</span>;
}

function CitedText({ children, sources }: { children: string; sources: AssistantSource[] }) {
  return <>{children.split(/(\[[A-Z][A-Z0-9_-]{0,31}\])/g).map((part, index): ReactNode => {
    const citation = part.slice(1, -1);
    return part.startsWith("[") && part.endsWith("]") && citationLabel.test(citation)
      ? <Citation key={index} citation={citation} sources={sources} />
      : part;
  })}</>;
}

function SourceCard({ source }: { source: AssistantSource }) {
  const href = sourceHref(source.url);
  const location = [source.kind === "task" ? "Project task" : source.kind === "meeting" ? "Meeting notes" : "Project file"];
  if (source.version !== null) location.push(`Version ${source.version}`);
  if (source.page !== null) location.push(`Page ${source.page}`);
  const normalize = (value: string) => value.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
  const locator = source.locator.trim();
  if (locator && ![location.join(" "), location.slice(1).join(" ")].some(value => normalize(value) === normalize(locator))) location.push(locator);
  return <article className="assistant-source" id={sourceTarget(source.citation)} tabIndex={-1}>
    <div className="assistant-source__heading"><span className="assistant-citation">[{source.citation}]</span><h4>{href ? <a href={href}>{source.title}</a> : source.title}</h4></div>
    <p className="assistant-source__location">{location.join(" · ")}</p>
    <blockquote className="assistant-source__excerpt">{source.excerpt}</blockquote>
    {href && <a className="assistant-source__open" href={href}>{source.kind === "task" ? "Open task" : "Open source"}<span className="sr-only"> {source.title}, {source.citation}</span><span aria-hidden="true"> ↗</span></a>}
  </article>;
}

function DraftCard({ draft, sources, projectId, onCreating }: { draft: AssistantDraft; sources: AssistantSource[]; projectId: string; onCreating: (busy: boolean) => void }) {
  const [title, setTitle] = useState(draft.title);
  const [description, setDescription] = useState(draft.description);
  const [busy, setBusy] = useState(false);
  const [locked, setLocked] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [created, setCreated] = useState<AssistantCreatedTask | null>(null);
  const requestEpoch = useRef(0);
  const pending = useRef<AbortController | null>(null);
  const confirmedRequest = useRef<AssistantTaskRequest | null>(null);
  const eligible = draft.can_create && Boolean(draft.approval_token);
  const valid = title.trim().length >= 3 && title.trim().length <= 120 && description.length <= 2000;
  useEffect(() => () => { requestEpoch.current += 1; pending.current?.abort(); }, []);

  const create = async () => {
    if (!eligible || !valid || busy || pending.current || created) return;
    const controller = new AbortController();
    const epoch = ++requestEpoch.current;
    const request = confirmedRequest.current ?? { approval_token: draft.approval_token, title: title.trim(), description };
    confirmedRequest.current = request;
    pending.current = controller;
    setLocked(true);
    setBusy(true);
    setError(null);
    onCreating(true);
    try {
      const value = await assistantApi.createTask(projectId, request, controller.signal);
      if (epoch === requestEpoch.current && !controller.signal.aborted) setCreated(value);
    } catch (value) {
      if (epoch === requestEpoch.current && !controller.signal.aborted) {
        setError(value);
        // A validation rejection creates no task, so the reviewed fields may
        // change. Ambiguous network/upstream failures keep the confirmed payload
        // fixed until the same token returns its idempotent task receipt.
        if (value instanceof APIError && value.status === 400) {
          confirmedRequest.current = null;
          setLocked(false);
        }
      }
    } finally {
      if (epoch === requestEpoch.current && !controller.signal.aborted) {
        pending.current = null;
        setBusy(false);
        onCreating(false);
      }
    }
  };
  const returnedHref = created ? sourceHref(created.task_url) : null;
  const expectedTaskPath = created ? `/app/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(created.task_id)}/` : "";
  const createdHref = returnedHref && new URL(returnedHref, window.location.origin).pathname === expectedTaskPath ? returnedHref : null;
  return <article className="assistant-draft">
    <div className="assistant-draft__heading"><h4>{created?.title ?? draft.title}</h4><span className={created ? "assistant-saved" : "assistant-unsaved"}>{created ? "Task created" : "Unsaved draft"}</span></div>
    {eligible && !created ? <div className="assistant-draft__editor">
      <Field label="Task title" hint="3–120 characters."><input name="draft_title" value={title} onChange={event => setTitle(event.target.value)} minLength={3} maxLength={120} required disabled={locked || busy} /></Field>
      <Field label="Task description" hint="Up to 2,000 characters."><textarea name="draft_description" className="assistant-draft__description" value={description} onChange={event => setDescription(event.target.value)} maxLength={2000} rows={3} disabled={locked || busy} /></Field>
    </div> : <p className="assistant-draft__description">{description}</p>}
    {draft.source_citations.length > 0 && <p className="assistant-draft__references">Based on {draft.source_citations.map((citation, index) => <span key={`${citation}-${index}`}><Citation citation={citation} sources={sources} />{index < draft.source_citations.length - 1 ? " " : ""}</span>)}</p>}
    {eligible && !created && <div className="assistant-draft__actions">
      <ConfirmAction triggerLabel={error ? "Retry create task" : "Create task"} triggerVariant="primary" confirmLabel="Confirm task creation" message={`Create “${confirmedRequest.current?.title ?? title.trim()}” in this project? Review its title and description before confirming.`} busy={busy || !valid} onConfirm={() => void create()} />
      {busy && <p role="status">Creating this task…</p>}
      {locked && !busy && !created && <p className="muted">Retry uses the same confirmed draft so it creates at most one task.</p>}
    </div>}
    {!eligible && !created && <p className="assistant-draft__readonly muted">Task creation is unavailable for this draft. You can still review its suggestion.</p>}
    {Boolean(error) && <ErrorState error={error} size="compact" />}
    {created && <div className="assistant-draft__receipt" role="status"><p>{created.created ? "Task created in this project." : "This task was already created. No duplicate was added."}</p>{createdHref && <a href={createdHref}>Open created task <span className="sr-only">{created.title}</span><span aria-hidden="true">↗</span></a>}</div>}
  </article>;
}

const resultNotices: Record<Exclude<AssistantResult["status"], "completed">, string> = {
  model_unavailable: "The model service is unavailable. You can search your project sources in Knowledge.",
  no_evidence: "The assistant did not find enough project evidence for this request. Try a more specific question or add relevant files and meeting notes.",
  invalid_response: "The assistant could not produce a response with valid source references. Try a more specific request.",
  limit_reached: "The assistant reached its limit before finishing. Review the available sources and try a narrower request.",
};

function Results({ result, projectId, onCreating }: { result: AssistantResult; projectId: string; onCreating: (busy: boolean) => void }) {
  const completed = result.status === "completed";
  const drafts = result.drafts.slice(0, 5);
  return <div className="page-stack assistant-results">
    <Panel labelledBy="assistant-results-heading">
      <div className="section-heading"><h3 id="assistant-results-heading">{completed ? "Assistant response" : "Assistant progress"}</h3><span>{result.sources.length} source{result.sources.length === 1 ? "" : "s"} checked</span></div>
      <p className="assistant-request">{result.question}</p>
      {completed && result.answer && <div className="assistant-answer-box"><p className="assistant-answer"><CitedText sources={result.sources}>{result.answer}</CitedText></p><p className="muted">Review the original sources before using this response.</p></div>}
      {!completed && <p className="assistant-notice" role="status">{resultNotices[result.status as Exclude<AssistantResult["status"], "completed">]}</p>}
      {result.status === "model_unavailable" && <Link to={`/app/projects/${projectId}/knowledge/`}>Open project knowledge</Link>}
      {result.warnings.length > 0 && <div className="assistant-warnings" role="status"><h4>Notes</h4><ul>{result.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></div>}
      {result.steps.length > 0 && <details className="assistant-steps" open><summary>What the assistant checked</summary><ol>{result.steps.map((step, index) => <li key={index}><strong>{toolLabels[step.tool] ?? "Reviewed project information"}</strong><p>{step.summary}</p><span className="muted">{step.result_count} result{step.result_count === 1 ? "" : "s"}</span></li>)}</ol></details>}
    </Panel>
    {completed && drafts.length > 0 && <Panel labelledBy="assistant-drafts-heading"><div className="section-heading"><h3 id="assistant-drafts-heading">Suggested task drafts</h3><span>{drafts.length} draft{drafts.length === 1 ? "" : "s"}</span></div><p className="muted">Review each suggestion and edit its details. A task is saved only after you confirm its creation.</p><div className="assistant-drafts">{drafts.map((draft, index) => <DraftCard key={draft.approval_token || index} draft={draft} sources={result.sources} projectId={projectId} onCreating={onCreating} />)}</div></Panel>}
    {result.sources.length > 0 && <Panel labelledBy="assistant-sources-heading"><h3 id="assistant-sources-heading">Sources and tasks</h3><div className="assistant-sources">{result.sources.map(source => <SourceCard key={source.citation} source={source} />)}</div></Panel>}
    {result.status === "no_evidence" && !result.sources.length && <EmptyState title="No matching project evidence">Use Knowledge to search documents directly, or check your current project tasks.</EmptyState>}
  </div>;
}

function ProjectAssistant({ projectId }: { projectId: string }) {
  const [settings, setSettings] = useState<AssistantSettings | null>(null);
  const [settingsError, setSettingsError] = useState<unknown>(null);
  const [settingsAttempt, setSettingsAttempt] = useState(0);
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AssistantResult | null>(null);
  const [requestError, setRequestError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [creatingDrafts, setCreatingDrafts] = useState(0);
  const creationCount = useRef(0);
  const requestEpoch = useRef(0);
  const requestAbort = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    setSettingsError(null);
    void assistantApi.settings(projectId, controller.signal).then(value => { if (current) setSettings(value); }).catch(error => {
      if (current && !controller.signal.aborted) setSettingsError(error);
    });
    return () => {
      current = false;
      controller.abort();
      requestEpoch.current += 1;
      requestAbort.current?.abort();
    };
  }, [projectId, settingsAttempt]);

  const run = async () => {
    const trimmed = question.trim();
    if (!settings?.available || !trimmed || trimmed.length > settings.max_question_length || busy || requestAbort.current || creationCount.current > 0) return;
    const epoch = ++requestEpoch.current;
    const controller = new AbortController();
    requestAbort.current = controller;
    setBusy(true);
    setRequestError(null);
    setResult(null);
    try {
      const value = await assistantApi.run(projectId, { question: trimmed }, controller.signal);
      if (epoch === requestEpoch.current && !controller.signal.aborted) setResult(value);
    } catch (error) {
      if (epoch === requestEpoch.current && !controller.signal.aborted) setRequestError(error);
    } finally {
      if (epoch === requestEpoch.current && !controller.signal.aborted) { setBusy(false); requestAbort.current = null; }
    }
  };
  const onSubmit = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); void run(); };
  const disabled = !settings?.available || busy || creatingDrafts > 0 || !question.trim() || question.trim().length > settings.max_question_length;
  const trackCreation = (pending: boolean) => {
    creationCount.current = Math.max(0, creationCount.current + (pending ? 1 : -1));
    setCreatingDrafts(creationCount.current);
  };
  return <div className="page-stack assistant-page">
    <div className="page-heading"><div><p className="eyebrow">Work from your project's evidence</p><h2>Project assistant</h2><p>Suggest actions; you decide which tasks to create.</p></div><Link className="button button--secondary" to={`/app/projects/${projectId}/knowledge/`}>Project knowledge</Link></div>
    {!settings && !settingsError && <Loading label="Opening project assistant…" />}
    {Boolean(settingsError) && <ErrorState error={settingsError} retry={() => setSettingsAttempt(value => value + 1)} />}
    {settings && <>
      <Panel labelledBy="assistant-compose-heading">
        <div className="section-heading"><h3 id="assistant-compose-heading">Ask the assistant</h3><span className="assistant-mode">{settings.available ? "Ready" : "Not configured"}</span></div>
        {settings.available && settings.notice && <p className="assistant-notice">{settings.notice}</p>}
        {!settings.available && <p className="assistant-unavailable" role="status">The assistant is waiting for its local setup to finish. You can search your project sources in <Link to={`/app/projects/${projectId}/knowledge/`}>Knowledge</Link> while it gets ready.</p>}
        <form className="assistant-form" onSubmit={onSubmit} aria-busy={busy}>
          <Field label="Assistant request" hint={`Describe what you want to find or plan. Up to ${settings.max_question_length} characters.`}><textarea name="question" value={question} onChange={event => setQuestion(event.target.value)} maxLength={settings.max_question_length} rows={3} required disabled={!settings.available || busy || creatingDrafts > 0} placeholder="Review our meeting decisions and current tasks. What should we work on next?" /></Field>
          <div className="form-actions"><Button type="submit" disabled={disabled}>{busy ? "Checking project information…" : settings.available ? "Ask project assistant" : "Assistant unavailable"}</Button></div>
        </form>
        <p className="assistant-scope muted">The assistant reads project sources, checks current tasks and suggests drafts. Review a draft and confirm it yourself to create a task.</p>
        {Boolean(requestError) && <ErrorState error={requestError} size="compact" />}
      </Panel>
      {busy && <Loading label="The assistant is checking your project sources and tasks…" size="compact" />}
      {result && <Results result={result} projectId={projectId} onCreating={trackCreation} />}
      {settings.available && !result && !busy && !requestError && <div className="assistant-start"><span aria-hidden="true">✦</span><p>Try a specific request about your team's work. The response will show its sources, checks and any unsaved task suggestions.</p></div>}
    </>}
  </div>;
}

export default function ProjectAssistantPage() {
  const { projectId = "" } = useParams();
  return <ProjectAssistant key={projectId} projectId={projectId} />;
}
