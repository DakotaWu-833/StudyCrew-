import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { assistantApi, type AssistantDraft, type AssistantResult, type AssistantSettings, type AssistantSource } from "../api/assistant";
import { Button, EmptyState, ErrorState, Field, Loading, Panel } from "../components/UI";
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

function DraftCard({ draft, sources }: { draft: AssistantDraft; sources: AssistantSource[] }) {
  return <article className="assistant-draft">
    <div className="assistant-draft__heading"><h4>{draft.title}</h4><span className="assistant-unsaved">Unsaved draft</span></div>
    <p className="assistant-draft__description">{draft.description}</p>
    {draft.source_citations.length > 0 && <p className="assistant-draft__references">Based on {draft.source_citations.map((citation, index) => <span key={`${citation}-${index}`}><Citation citation={citation} sources={sources} />{index < draft.source_citations.length - 1 ? " " : ""}</span>)}</p>}
  </article>;
}

const resultNotices: Record<Exclude<AssistantResult["status"], "completed">, string> = {
  model_unavailable: "The model service is unavailable. You can search your project sources in Knowledge.",
  no_evidence: "The assistant did not find enough project evidence for this request. Try a more specific question or add relevant files and meeting notes.",
  invalid_response: "The assistant could not produce a response with valid source references. Try a more specific request.",
  limit_reached: "The assistant reached its limit before finishing. Review the available sources and try a narrower request.",
};

function Results({ result, projectId }: { result: AssistantResult; projectId: string }) {
  const completed = result.status === "completed";
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
    {completed && result.drafts.length > 0 && <Panel labelledBy="assistant-drafts-heading"><div className="section-heading"><h3 id="assistant-drafts-heading">Suggested task drafts</h3><span>{result.drafts.length} draft{result.drafts.length === 1 ? "" : "s"}</span></div><p className="muted">These suggestions have not been saved. Review and copy any useful text when you create a task.</p><div className="assistant-drafts">{result.drafts.map((draft, index) => <DraftCard key={index} draft={draft} sources={result.sources} />)}</div></Panel>}
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
    if (!settings?.available || !trimmed || trimmed.length > settings.max_question_length || busy || requestAbort.current) return;
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
  const disabled = !settings?.available || busy || !question.trim() || question.trim().length > settings.max_question_length;
  return <div className="page-stack assistant-page">
    <div className="page-heading"><div><p className="eyebrow">Work from your project's evidence</p><h2>Project assistant</h2><p>Check your team's sources and current tasks, then prepare suggestions for the next steps.</p></div><Link className="button button--secondary" to={`/app/projects/${projectId}/knowledge/`}>Project knowledge</Link></div>
    {!settings && !settingsError && <Loading label="Opening project assistant…" />}
    {Boolean(settingsError) && <ErrorState error={settingsError} retry={() => setSettingsAttempt(value => value + 1)} />}
    {settings && <>
      <Panel labelledBy="assistant-compose-heading">
        <div className="section-heading"><h3 id="assistant-compose-heading">Ask the assistant</h3><span className="assistant-mode">{settings.available ? "Ready" : "Not configured"}</span></div>
        {settings.notice && <p className="assistant-notice">{settings.notice}</p>}
        {!settings.available && <p className="assistant-unavailable" role="status">The assistant needs a configured model service. You can still search your project sources in <Link to={`/app/projects/${projectId}/knowledge/`}>Knowledge</Link>.</p>}
        <form className="assistant-form" onSubmit={onSubmit} aria-busy={busy}>
          <Field label="Assistant request" hint={`Describe what you want to find or plan. Up to ${settings.max_question_length} characters.`}><textarea name="question" value={question} onChange={event => setQuestion(event.target.value)} maxLength={settings.max_question_length} rows={3} required disabled={!settings.available || busy} placeholder="Review our meeting decisions and current tasks. What should we work on next?" /></Field>
          <div className="form-actions"><Button type="submit" disabled={disabled}>{busy ? "Checking project information…" : settings.available ? "Ask project assistant" : "Assistant unavailable"}</Button></div>
        </form>
        <p className="assistant-scope muted">The assistant can read project sources, check current tasks and suggest task drafts. Suggestions are not saved, and your project is not changed.</p>
        {Boolean(requestError) && <ErrorState error={requestError} size="compact" />}
      </Panel>
      {busy && <Loading label="The assistant is checking your project sources and tasks…" size="compact" />}
      {result && <Results result={result} projectId={projectId} />}
      {settings.available && !result && !busy && !requestError && <div className="assistant-start"><span aria-hidden="true">✦</span><p>Try a specific request about your team's work. The response will show its sources, checks and any unsaved task suggestions.</p></div>}
    </>}
  </div>;
}

export default function ProjectAssistantPage() {
  const { projectId = "" } = useParams();
  return <ProjectAssistant key={projectId} projectId={projectId} />;
}
