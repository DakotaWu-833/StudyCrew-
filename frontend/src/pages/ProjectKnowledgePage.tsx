import { useEffect, useRef, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { knowledgeApi, type KnowledgeAnswer, type KnowledgeSearch, type KnowledgeSettings, type KnowledgeSource } from "../api/knowledge";
import { Button, EmptyState, ErrorState, Field, Loading, Panel } from "../components/UI";
import "./project-knowledge.css";

function sourceHref(value: string): string | null {
  if (!value) return null;
  try {
    const url = new URL(value, window.location.origin);
    if (!["http:", "https:"].includes(url.protocol) || url.origin !== window.location.origin) return null;
    return `${url.pathname}${url.search}${url.hash}`;
  } catch { return null; }
}

function SourceCard({ source }: { source: KnowledgeSource }) {
  const href = sourceHref(source.url);
  const location = [source.kind === "file" ? "Project file" : "Meeting notes"];
  if (source.version !== null) location.push(`Version ${source.version}`);
  if (source.page !== null) location.push(`Page ${source.page}`);
  const normalize = (value: string) => value.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
  const locator = source.locator.trim();
  if (locator && ![location.join(" "), location.slice(1).join(" ")].some(value => normalize(value) === normalize(locator))) location.push(locator);
  return <article className="knowledge-source" id={`knowledge-source-${source.citation}`} tabIndex={-1}>
    <div className="knowledge-source__heading">
      <span className="knowledge-citation">[{source.citation}]</span>
      <h4>{href ? <a href={href}>{source.title}</a> : source.title}</h4>
    </div>
    <p className="knowledge-source__location">{location.join(" · ")}</p>
    <blockquote className="knowledge-excerpt">{source.excerpt}</blockquote>
    {href && <a className="knowledge-source__open" href={href}>Open source <span className="sr-only">{source.title}, {source.citation}</span><span aria-hidden="true">↗</span></a>}
  </article>;
}

function CitedAnswer({ answer, sources }: { answer: string; sources: KnowledgeSource[] }) {
  const citations = new Set(sources.map(source => source.citation));
  return <p className="knowledge-answer">{answer.split(/(\[S\d+\])/g).map((part, index) => {
    const citation = part.slice(1, -1);
    return /^\[S\d+\]$/.test(part) && citations.has(citation)
      ? <a key={index} href={`#knowledge-source-${citation}`} aria-label={`Read source ${citation}`}>{part}</a>
      : part;
  })}</p>;
}

function Results({ result }: { result: KnowledgeSearch | KnowledgeAnswer }) {
  const answer = "status" in result ? result : null;
  return <Panel className="knowledge-results" labelledBy="knowledge-results-heading">
    <div className="section-heading"><h3 id="knowledge-results-heading">{answer?.status === "answered" ? "Answer and sources" : "Project sources"}</h3><span>{result.sources.length} source{result.sources.length === 1 ? "" : "s"}</span></div>
    <p className="knowledge-question">{result.question}</p>
    {answer?.status === "answered" && answer.answer && <div className="knowledge-answer-box"><CitedAnswer answer={answer.answer} sources={result.sources} /><p className="muted">Check the cited sources before using this answer.</p></div>}
    {answer?.status === "model_unavailable" && <p className="knowledge-notice" role="status">An answer could not be generated. You can still review the matching sources below.</p>}
    {answer?.status === "unverified_answer" && <p className="knowledge-notice" role="status">The generated answer did not include valid source citations and was withheld. Review the project sources below.</p>}
    {result.limited && <p className="knowledge-notice" role="status">Only part of this project's material was searched. Review the warnings and original sources.</p>}
    {result.warnings.length > 0 && <div className="knowledge-warnings" role="status"><h4>Search notes</h4><ul>{result.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></div>}
    {!result.sources.length ? <EmptyState title="No matching project sources">Try a specific phrase from your files or meeting notes. Add relevant documents in Files if the project has no searchable material.</EmptyState> : <div className="knowledge-sources">{result.sources.map(source => <SourceCard key={source.citation} source={source} />)}</div>}
  </Panel>;
}

function ProjectKnowledge({ projectId }: { projectId: string }) {
  const [settings, setSettings] = useState<KnowledgeSettings | null>(null);
  const [settingsError, setSettingsError] = useState<unknown>(null);
  const [settingsAttempt, setSettingsAttempt] = useState(0);
  const [question, setQuestion] = useState("");
  const [maxSources, setMaxSources] = useState(5);
  const [result, setResult] = useState<KnowledgeSearch | KnowledgeAnswer | null>(null);
  const [requestError, setRequestError] = useState<unknown>(null);
  const [busy, setBusy] = useState<"ask" | "search" | null>(null);
  const requestEpoch = useRef(0);
  const requestAbort = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    setSettingsError(null);
    void knowledgeApi.settings(projectId, controller.signal).then(value => {
      if (current) setSettings(value);
    }).catch(error => {
      if (current && !controller.signal.aborted) setSettingsError(error);
    });
    return () => {
      current = false;
      controller.abort();
      requestEpoch.current += 1;
      requestAbort.current?.abort();
    };
  }, [projectId, settingsAttempt]);

  const run = async (mode: "ask" | "search") => {
    const trimmed = question.trim();
    if (!settings || !trimmed || trimmed.length > settings.max_question_length || busy || requestAbort.current || (mode === "ask" && !settings.generation_available)) return;
    const epoch = ++requestEpoch.current;
    const controller = new AbortController();
    requestAbort.current = controller;
    setBusy(mode);
    setRequestError(null);
    setResult(null);
    try {
      const value = await knowledgeApi[mode](projectId, { question: trimmed, max_sources: maxSources }, controller.signal);
      if (epoch === requestEpoch.current && !controller.signal.aborted) setResult(value);
    } catch (error) {
      if (epoch === requestEpoch.current && !controller.signal.aborted) setRequestError(error);
    } finally {
      if (epoch === requestEpoch.current && !controller.signal.aborted) {
        setBusy(null);
        requestAbort.current = null;
      }
    }
  };
  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void run(settings?.generation_available ? "ask" : "search");
  };
  const disabled = !question.trim() || Boolean(busy) || question.trim().length > (settings?.max_question_length ?? 1000);

  return <div className="page-stack knowledge-page">
    <div className="page-heading"><div><p className="eyebrow">Your team's sources</p><h2>Project knowledge</h2><p>Find project requirements, meeting decisions and details in your team's documents.</p></div></div>
    {!settings && !settingsError && <Loading label="Opening project knowledge…" />}
    {Boolean(settingsError) && <ErrorState error={settingsError} retry={() => setSettingsAttempt(value => value + 1)} />}
    {settings && <>
      <Panel labelledBy="knowledge-compose-heading">
        <div className="section-heading"><h3 id="knowledge-compose-heading">{settings.generation_available ? "Ask about your project" : "Search project sources"}</h3><span className="knowledge-mode">{settings.generation_available ? "Answers with citations" : "Source search"}</span></div>
        {settings.notice && <p className="knowledge-notice">{settings.notice}</p>}
        {!settings.generation_available && <p className="knowledge-search-only">Answer generation is not configured. Search returns excerpts from your project sources.</p>}
        <form className="knowledge-form" onSubmit={onSubmit} aria-busy={Boolean(busy)}>
          <Field label="Project question" hint={`Be specific. Up to ${settings.max_question_length} characters.`}>
            <textarea name="question" value={question} onChange={event => setQuestion(event.target.value)} maxLength={settings.max_question_length} rows={3} required disabled={Boolean(busy)} placeholder="What does the assignment require for our final report?" />
          </Field>
          <div className="knowledge-form__footer">
            <Field label="Maximum sources"><select name="max_sources" value={maxSources} onChange={event => setMaxSources(Number(event.target.value))} disabled={Boolean(busy)}>{[3, 5, 6].map(count => <option key={count} value={count}>{count} sources</option>)}</select></Field>
            <div className="form-actions">
              <Button type="submit" disabled={disabled}>{busy ? (busy === "ask" ? "Finding an answer…" : "Searching sources…") : settings.generation_available ? "Ask project question" : "Search project sources"}</Button>
              {settings.generation_available && <Button type="button" variant="secondary" disabled={disabled} onClick={() => void run("search")}>Search sources only</Button>}
            </div>
          </div>
        </form>
        <p className="knowledge-scope muted">Search covers the latest TXT, CSV, text-based PDF and DOCX files, plus meeting notes. Scanned PDFs and images are not searchable. Only sources you can access in this project are included.</p>
        {Boolean(requestError) && <ErrorState error={requestError} size="compact" />}
      </Panel>
      {busy && <Loading label={busy === "ask" ? "Checking project sources and generating an answer…" : "Searching your project sources…"} size="compact" />}
      {result && <Results result={result} />}
      {!result && !busy && !requestError && <div className="knowledge-start"><span aria-hidden="true">⌕</span><p>Start with a question about this project. Your results will appear here with their original sources.</p></div>}
    </>}
  </div>;
}

export default function ProjectKnowledgePage() {
  const { projectId = "" } = useParams();
  // A fresh instance also isolates a previous visit to A after A → B → A.
  return <ProjectKnowledge key={projectId} projectId={projectId} />;
}
