import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ProjectChatPage from "./ProjectChatPage";
import { chatApi, type ChatMessage, type ChatState } from "../api/chat";

vi.mock("../api/chat", () => ({ chatApi: { list: vi.fn(), send: vi.fn(), remove: vi.fn(), presence: vi.fn() } }));

let container: HTMLDivElement, root: Root;
const when = "2026-10-02T01:00:00Z";
const message = (id: string, body: string, values: Partial<ChatMessage> = {}): ChatMessage => ({
  id, body, author: { id: "teammate", display_name: "Teammate" }, created_at: when, updated_at: when,
  removed: false, hidden: false, can_remove: false, ...values,
});
const feed = (messages: ChatMessage[] = [], values: Partial<ChatState> = {}): ChatState => ({
  messages, cursor: 1, has_more: false, older_than: null, online: [], read_only: false, poll_seconds: 2,
  visibility_key: "unblocked", ...values,
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (value: unknown) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}
function Navigation() {
  const navigate = useNavigate();
  return <><button onClick={() => navigate("/projects/A/chat")}>Open A</button><button onClick={() => navigate("/projects/B/chat")}>Open B</button></>;
}
async function render() {
  await act(async () => root.render(<MemoryRouter initialEntries={["/projects/A/chat"]}><Navigation /><Routes><Route path="/projects/:projectId/chat" element={<ProjectChatPage />} /></Routes></MemoryRouter>));
}
async function click(text: string) {
  const button = [...container.querySelectorAll<HTMLButtonElement>("button")].find(row => row.textContent === text);
  expect(button, `Missing button ${text}`).toBeDefined();
  await act(async () => { button!.click(); });
}
async function compose(body: string) {
  const textarea = container.querySelector("textarea")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(textarea, body);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function advance(milliseconds: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(milliseconds); });
}

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.useFakeTimers(); vi.resetAllMocks();
  vi.mocked(chatApi.list).mockResolvedValue(feed());
  vi.mocked(chatApi.presence).mockResolvedValue(undefined);
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.useRealTimers(); });

it("keeps a failed send draft and retries with the same nonce to avoid duplicate messages", async () => {
  vi.mocked(chatApi.send).mockRejectedValueOnce(new Error("Connection interrupted")).mockResolvedValueOnce(message("sent", "One update"));
  await render(); await compose("One update"); await click("Send message");
  expect(container.querySelector("textarea")?.value).toBe("One update");
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("Connection interrupted");
  await click("Send message");
  expect(chatApi.send).toHaveBeenCalledTimes(2);
  expect(vi.mocked(chatApi.send).mock.calls[1]![2]).toBe(vi.mocked(chatApi.send).mock.calls[0]![2]);
  expect(container.querySelector("textarea")?.value).toBe("");
  expect([...container.querySelectorAll(".chat-message")].map(row => row.textContent).filter(text => text?.includes("One update"))).toHaveLength(1);
});

it("replaces withdrawn content with a tombstone and rejects older poll content", async () => {
  const original = message("removable", "Withdraw this message", { can_remove: true });
  vi.mocked(chatApi.list).mockResolvedValueOnce(feed([original])).mockResolvedValue(feed([original], { cursor: 2 }));
  vi.mocked(chatApi.remove).mockResolvedValue({ ...original, body: "", removed: true, hidden: true, can_remove: false, updated_at: "2026-10-02T01:01:00Z" });
  await render(); await click("Remove message");
  expect(chatApi.remove).toHaveBeenCalledWith("A", original, "Message withdrawn from project chat");
  expect(container.textContent).toContain("Message removed"); expect(container.textContent).not.toContain("Withdraw this message");
  await advance(2000);
  expect(container.textContent).toContain("Message removed"); expect(container.textContent).not.toContain("Withdraw this message");
});

it("ignores an initial A response that arrives after navigating to project B", async () => {
  const old = deferred<ChatState>();
  vi.mocked(chatApi.list).mockImplementation(project => project === "A" ? old.promise : Promise.resolve(feed([message("B", "Private B message")])));
  await render(); await click("Open B");
  await act(async () => { old.resolve(feed([message("A", "Private A message")])); });
  expect(container.textContent).toContain("Private B message"); expect(container.textContent).not.toContain("Private A message");
});

it("ignores a send response from A after navigating to project B and clears A's draft", async () => {
  const old = deferred<ChatMessage>();
  vi.mocked(chatApi.send).mockReturnValue(old.promise);
  vi.mocked(chatApi.list).mockImplementation(project => Promise.resolve(feed([message(project, `${project} history`)])));
  await render(); await compose("A pending send"); await click("Send message"); await click("Open B");
  expect(container.querySelector("textarea")?.value).toBe("");
  await act(async () => { old.resolve(message("sent-A", "A pending send")); });
  expect(container.textContent).toContain("B history"); expect(container.textContent).not.toContain("A pending send");
  expect(container.querySelector<HTMLButtonElement>('button[type="submit"]')?.disabled).toBe(true);
});

it("preserves a new draft when an old send resolves after leaving A and returning to A", async () => {
  const old = deferred<ChatMessage>();
  vi.mocked(chatApi.send).mockReturnValue(old.promise);
  await render(); await compose("Previous A visit"); await click("Send message");
  await click("Open B"); await click("Open A"); await compose("Current A draft");
  await act(async () => { old.resolve(message("previous-A", "Previous A visit")); });
  expect(container.querySelector("textarea")?.value).toBe("Current A draft");
  expect(container.textContent).not.toContain("Previous A visit");
  expect(container.querySelector<HTMLButtonElement>('button[type="submit"]')?.disabled).toBe(false);
});

it("ignores delayed older history from A after navigating to project B", async () => {
  const old = deferred<ChatState>();
  vi.mocked(chatApi.list).mockImplementation((project, params) => params?.before ? old.promise : Promise.resolve(feed([message(project, `${project} history`)], { older_than: project === "A" ? "older-A" : null })));
  await render(); await click("Load earlier messages"); await click("Open B");
  await act(async () => { old.resolve(feed([message("older", "A older secret")])); });
  expect(container.textContent).toContain("B history"); expect(container.textContent).not.toContain("A older secret");
});

it("preserves the visible reading position when older messages are prepended and scrolls for new messages", async () => {
  const previousDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollIntoView");
  const scrollToMessage = vi.fn();
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, writable: true, value: scrollToMessage });
  const recent = message("recent", "Recent message");
  const earlier = message("earlier", "Earlier message", { created_at: "2026-10-01T23:00:00Z" });
  const newest = message("newest", "Newly received message", { created_at: "2026-10-02T02:00:00Z" });
  vi.mocked(chatApi.list).mockResolvedValueOnce(feed([recent], { older_than: "older-A" }))
    .mockResolvedValueOnce(feed([earlier]))
    .mockResolvedValue(feed([newest], { cursor: 2 }));
  try {
    await render();
    expect(scrollToMessage).toHaveBeenCalledOnce();
    scrollToMessage.mockClear();
    const log = container.querySelector<HTMLDivElement>(".chat-messages")!;
    Object.defineProperty(log, "scrollHeight", { configurable: true, get: () => log.querySelectorAll(".chat-message").length * 200 });
    log.scrollTop = 40;
    await click("Load earlier messages");
    expect(log.querySelector(".chat-message")?.textContent).toContain("Earlier message");
    expect(log.scrollTop).toBe(240);
    expect(scrollToMessage).not.toHaveBeenCalled();
    await advance(2000);
    expect(container.textContent).toContain("Newly received message");
    expect(scrollToMessage).toHaveBeenCalledOnce();
  } finally {
    if (previousDescriptor) Object.defineProperty(HTMLElement.prototype, "scrollIntoView", previousDescriptor);
    else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
  }
});

it("refreshes the complete feed when block and unblock visibility changes", async () => {
  const original = message("visible", "Teammate message");
  const blocked = { ...original, body: "", hidden: true };
  vi.mocked(chatApi.list)
    .mockResolvedValueOnce(feed([original]))
    .mockResolvedValueOnce(feed([], { cursor: 2, visibility_key: "blocked" }))
    .mockResolvedValueOnce(feed([blocked], { cursor: 2, visibility_key: "blocked" }))
    .mockResolvedValueOnce(feed([], { cursor: 3, visibility_key: "unblocked-again" }))
    .mockResolvedValue(feed([original], { cursor: 3, visibility_key: "unblocked-again" }));
  await render(); expect(container.textContent).toContain("Teammate message");
  await advance(2001);
  expect(container.textContent).not.toContain("Teammate message"); expect(container.textContent).toContain("Message hidden by your block settings");
  expect(vi.mocked(chatApi.list).mock.calls[2]).toEqual(["A", {}]);
  await advance(2001);
  expect(container.textContent).toContain("Teammate message"); expect(container.textContent).not.toContain("Message hidden by your block settings");
  expect(vi.mocked(chatApi.list).mock.calls[4]).toEqual(["A", {}]);
});

it("does not reintroduce unblocked history when an older request resolves after a block change", async () => {
  const old = deferred<ChatState>();
  let polls = 0;
  vi.mocked(chatApi.list).mockImplementation((_project, params) => {
    if (params?.before) return old.promise;
    polls += 1;
    if (polls === 1) return Promise.resolve(feed([message("latest", "Recent teammate message")], { older_than: "older-A" }));
    return Promise.resolve(feed([message("latest", "", { hidden: true })], { cursor: 2, visibility_key: "blocked" }));
  });
  await render(); await click("Load earlier messages"); await advance(2001);
  expect(container.textContent).toContain("Message hidden by your block settings");
  await act(async () => { old.resolve(feed([message("older", "Blocked teammate older secret")], { visibility_key: "unblocked" })); });
  expect(container.textContent).not.toContain("Blocked teammate older secret");
});
