import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { chatApi, type ChatMessage, type ChatState } from "../api/chat";
import { errorMessage } from "../api/client";
import { Button, EmptyState, Loading, Panel } from "../components/UI";
import { formatDate } from "../app/format";
import "./project-chat.css";

export function mergeMessages(previous: ChatMessage[], incoming: ChatMessage[]) {
  const rows = new Map(previous.map(row => [row.id, row]));
  for (const row of incoming) {
    const old = rows.get(row.id);
    if (!old || row.updated_at >= old.updated_at) rows.set(row.id, row);
  }
  return [...rows.values()].sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id));
}

export default function ProjectChatPage() {
  const { projectId = "" } = useParams();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [state, setState] = useState<ChatState>();
  const [body, setBody] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [older, setOlder] = useState<string | null>(null);
  const nonce = useRef<{ body: string; value: string } | undefined>(undefined);
  const cursor = useRef<number | undefined>(undefined);
  const visibility = useRef<string | undefined>(undefined);
  const messageList = useRef<HTMLDivElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const latestMessage = useRef<string | undefined>(undefined);
  const historyScroll = useRef<{ top: number; height: number } | undefined>(undefined);
  const currentProject = useRef(projectId);
  const projectEpoch = useRef(0);
  if (currentProject.current !== projectId) { currentProject.current = projectId; projectEpoch.current += 1; }
  useEffect(() => {
    let cancelled = false, timer: ReturnType<typeof setTimeout>;
    cursor.current = undefined;
    visibility.current = undefined;
    latestMessage.current = undefined;
    historyScroll.current = undefined;
    nonce.current = undefined; setBody(""); setBusy(false);
    setLoading(true); setMessages([]); setOlder(null); setState(undefined);
    const update = async () => {
      try {
        const first = cursor.current === undefined;
        const result = await chatApi.list(projectId, first ? {} : { since: cursor.current });
        if (cancelled) return;
        if (visibility.current !== undefined && visibility.current !== result.visibility_key) {
          visibility.current = result.visibility_key; cursor.current = undefined; setMessages([]); setOlder(null);
          timer = setTimeout(update, 0); return;
        }
        visibility.current = result.visibility_key;
        setState(result); setMessages(rows => mergeMessages(rows, result.messages)); cursor.current = result.cursor;
        if (first) setOlder(result.older_than);
        setError(""); setLoading(false);
        timer = setTimeout(update, result.has_more && !first ? 0 : document.hidden ? 10000 : 2000);
      } catch (value) {
        if (cancelled) return;
        setError(errorMessage(value)); setLoading(false);
        timer = setTimeout(update, 5000);
      }
    };
    void update();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [projectId]);
  useEffect(() => {
    let cancelled = false;
    const pulse = () => { if (!document.hidden && navigator.onLine && !state?.read_only) void chatApi.presence(projectId).catch(() => { if (!cancelled) { /* next poll shows current authorization */ } }); };
    pulse(); const timer = setInterval(pulse, 15000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [projectId, state?.read_only]);
  useLayoutEffect(() => {
    const latest = messages.at(-1)?.id;
    const position = historyScroll.current;
    if (position && messageList.current) {
      messageList.current.scrollTop = position.top + messageList.current.scrollHeight - position.height;
      historyScroll.current = undefined;
    } else if (latest && latest !== latestMessage.current) {
      bottom.current?.scrollIntoView?.({ block: "nearest" });
    }
    latestMessage.current = latest;
  }, [messages]);
  const send = async () => {
    const sentProject = projectId;
    const sentEpoch = projectEpoch.current;
    const text = body.trim(); if (!text || busy) return;
    if (nonce.current?.body !== text) nonce.current = { body: text, value: crypto.randomUUID() };
    setBusy(true); setError("");
    try { const row = await chatApi.send(projectId, text, nonce.current.value); if (currentProject.current !== sentProject || projectEpoch.current !== sentEpoch) return; setMessages(rows => mergeMessages(rows, [row])); setBody(""); nonce.current = undefined; }
    catch (value) { if (currentProject.current === sentProject && projectEpoch.current === sentEpoch) setError(errorMessage(value)); }
    finally { if (currentProject.current === sentProject && projectEpoch.current === sentEpoch) setBusy(false); }
  };
  const remove = async (row: ChatMessage) => {
    const sentProject = projectId;
    const sentEpoch = projectEpoch.current;
    setBusy(true);
    try { const result = await chatApi.remove(projectId, row, "Message withdrawn from project chat"); if (currentProject.current === sentProject && projectEpoch.current === sentEpoch) setMessages(rows => mergeMessages(rows, [result])); }
    catch (value) { if (currentProject.current === sentProject && projectEpoch.current === sentEpoch) setError(errorMessage(value)); }
    finally { if (currentProject.current === sentProject && projectEpoch.current === sentEpoch) setBusy(false); }
  };
  const loadOlder = async () => {
    const sentProject = projectId;
    const sentEpoch = projectEpoch.current;
    const sentVisibility = visibility.current;
    if (!older) return; setBusy(true);
    try { const result = await chatApi.list(projectId, { before: older }); if (currentProject.current !== sentProject || projectEpoch.current !== sentEpoch || visibility.current !== sentVisibility || result.visibility_key !== sentVisibility) return; if (messageList.current) historyScroll.current = { top: messageList.current.scrollTop, height: messageList.current.scrollHeight }; setMessages(rows => mergeMessages(rows, result.messages)); setOlder(result.older_than); }
    catch (value) { if (currentProject.current === sentProject && projectEpoch.current === sentEpoch) setError(errorMessage(value)); }
    finally { if (currentProject.current === sentProject && projectEpoch.current === sentEpoch) setBusy(false); }
  };
  return <div className="page-stack"><div className="page-heading"><div><h2>Project chat</h2><p>Messages update automatically while this page is open.</p></div></div>
    {error && <p className="notice notice--error" role="alert">{error}</p>}
    <Panel><div className="chat-presence" aria-label="Online teammates"><strong>Online now</strong>{state?.online.length ? state.online.map(user => <span key={user.id}>{user.display_name}</span>) : <span className="muted">No active teammates</span>}</div>
      {older && <Button variant="quiet" disabled={busy} onClick={() => void loadOlder()}>Load earlier messages</Button>}
      {loading ? <Loading label="Opening project chat…" /> : !messages.length ? <EmptyState title="Start the conversation">Share a quick update or ask your teammates a question.</EmptyState> : <div ref={messageList} className="chat-messages" role="log" aria-label="Project messages" aria-live="polite">{messages.map(row => <article className="chat-message" key={row.id}>
        <div className="chat-message__heading"><strong>{row.author.display_name}</strong><time dateTime={row.created_at}>{formatDate(row.created_at)}</time></div>
        <p className="prose">{row.hidden ? <em>{row.removed ? "Message removed" : "Message hidden by your block settings"}</em> : row.body}</p>
        {!state?.read_only && row.can_remove && <Button variant="quiet" disabled={busy} onClick={() => void remove(row)}>Remove message</Button>}
      </article>)}<div ref={bottom} /></div>}
      {state?.read_only ? <p className="notice">This project is archived. Chat history is read-only.</p> : <form className="chat-compose" onSubmit={event => { event.preventDefault(); void send(); }}><label className="field"><span>Message</span><textarea value={body} onChange={event => setBody(event.target.value)} required maxLength={2000} rows={3} disabled={busy} /></label><Button type="submit" disabled={busy || !body.trim() || loading}>{busy ? "Sending…" : "Send message"}</Button></form>}
    </Panel></div>;
}
