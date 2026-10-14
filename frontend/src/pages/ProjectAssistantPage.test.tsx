import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { assistantApi, type AssistantCreatedTask, type AssistantResult, type AssistantSettings } from "../api/assistant";
import { APIError } from "../api/client";
import ProjectAssistantPage from "./ProjectAssistantPage";

vi.mock("../api/assistant", () => ({ assistantApi: { settings: vi.fn(), run: vi.fn(), createTask: vi.fn() } }));
const settings: AssistantSettings = { available: false, notice: "The assistant needs a model that supports tools.", tools: ["search_project_sources", "list_project_tasks", "propose_tasks"], max_question_length: 1000, max_steps: 4 };
const completed: AssistantResult = {
  question: "What should we work on next?", status: "completed", answer: "Prepare the final diagram [S1], after checking the existing review task [S2].", model: "configured-model", warnings: [],
  sources: [
    { citation: "S1", kind: "meeting", source_id: "notes", title: "Design review", version: 2, page: null, excerpt: "Prepare a final design diagram.", url: "/app/projects/A/coordination/?meeting=meeting-a", locator: "Meeting notes, version 2" },
    { citation: "S2", kind: "task", source_id: "task-a", title: "Review the design", version: null, page: null, excerpt: "Status: in progress. Review the proposed design.", url: "/app/projects/A/tasks/task-a/", locator: "Current task" },
  ],
  drafts: [{ title: "Prepare final diagram", description: "Create a diagram based on the meeting decision.", source_citations: ["S1"], approval_token: "signed-draft-token", can_create: true }],
  steps: [
    { tool: "search_project_sources", summary: "Found the design review notes.", result_count: 1 },
    { tool: "list_project_tasks", summary: "Checked the existing design review task.", result_count: 1 },
    { tool: "propose_tasks", summary: "Prepared one suggested task.", result_count: 1 },
  ],
};
const createdTask: AssistantCreatedTask = { task_id: "created-task", title: "Prepare final diagram", created: true, task_url: "/app/projects/A/tasks/created-task/" };

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(yes => { resolve = yes; });
  return { promise, resolve };
}
function Navigation() {
  const navigate = useNavigate();
  return <><button onClick={() => navigate("/projects/A/assistant")}>Open A</button><button onClick={() => navigate("/projects/B/assistant")}>Open B</button></>;
}
let root: Root, container: HTMLDivElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.resetAllMocks();
  vi.mocked(assistantApi.settings).mockResolvedValue(settings);
  vi.mocked(assistantApi.run).mockResolvedValue(completed);
  vi.mocked(assistantApi.createTask).mockResolvedValue(createdTask);
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value() { this.open = true; } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value() { this.open = false; } });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
async function render() {
  await act(async () => root.render(<MemoryRouter initialEntries={["/projects/A/assistant"]}><Navigation /><Routes><Route path="/projects/:projectId/assistant" element={<ProjectAssistantPage />} /></Routes></MemoryRouter>));
}
function button(name: string) {
  const found = [...container.querySelectorAll<HTMLButtonElement>("button")].find(row => row.textContent === name);
  expect(found, `Missing button ${name}`).toBeDefined(); return found!;
}
async function click(name: string) { await act(async () => { button(name).click(); }); }
async function compose(value: string) {
  const textarea = container.querySelector("textarea")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(textarea, value);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
function configure() { vi.mocked(assistantApi.settings).mockResolvedValue({ ...settings, available: true }); }
async function editDraft(title: string, description: string) {
  await act(async () => {
    const titleInput = container.querySelector<HTMLInputElement>('[name="draft_title"]')!;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(titleInput, title);
    titleInput.dispatchEvent(new Event("input", { bubbles: true }));
    const textarea = container.querySelector<HTMLTextAreaElement>('[name="draft_description"]')!;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(textarea, description);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function getDraft() { configure(); await render(); await compose("Question"); await click("Ask project assistant"); }

it("clearly disables an unconfigured assistant and directs the user to Knowledge without fake output", async () => {
  await render();
  expect(container.textContent).toContain("The assistant is waiting for its local setup to finish");
  expect(button("Assistant unavailable").disabled).toBe(true);
  expect(container.querySelector("textarea")?.disabled).toBe(true);
  expect(container.querySelector('a[href="/app/projects/A/knowledge/"]')).not.toBeNull();
  await act(async () => { container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
  expect(assistantApi.run).not.toHaveBeenCalled();
  expect(container.querySelector(".assistant-results")).toBeNull();
});

it("shows cited responses, task references, readable checks and unsaved drafts without creating tasks", async () => {
  const storage = vi.spyOn(Storage.prototype, "setItem");
  try {
    configure(); await render(); await compose("  What should we work on next?  "); await click("Ask project assistant");
    expect(assistantApi.run).toHaveBeenCalledWith("A", { question: completed.question }, expect.any(AbortSignal));
    expect(assistantApi.run).toHaveBeenCalledOnce();
    expect(container.querySelector(".assistant-answer")?.textContent).toBe(completed.answer);
    expect([...container.querySelectorAll<HTMLAnchorElement>(".assistant-answer a")].map(row => row.getAttribute("href"))).toEqual(["#assistant-source-S1", "#assistant-source-S2"]);
    expect(container.querySelector("#assistant-source-S2")?.textContent).toContain("Project task · Current task");
    expect(container.querySelector('a[href="/app/projects/A/tasks/task-a/"]')).not.toBeNull();
    expect(container.querySelector(".assistant-draft")?.textContent).toContain("Unsaved draft");
    expect(container.querySelector<HTMLTextAreaElement>(".assistant-draft__description")?.value).toBe(completed.drafts[0]!.description);
    expect(container.querySelector<HTMLAnchorElement>(".assistant-draft__references a")?.getAttribute("href")).toBe("#assistant-source-S1");
    expect(container.querySelector(".assistant-steps")?.textContent).toContain("Checked project tasks");
    expect(container.querySelector(".assistant-steps")?.textContent).toContain("Prepared task drafts");
    expect(container.querySelector('[name="title"]')).toBeNull();
    expect(button("Create task")).toBeDefined();
    expect(assistantApi.createTask).not.toHaveBeenCalled();
    expect(storage).not.toHaveBeenCalled();
  } finally { storage.mockRestore(); }
});

it("renders answer, draft, tool and source markup literally and blocks unsafe or external links", async () => {
  configure();
  vi.mocked(assistantApi.run).mockResolvedValue({ ...completed,
    answer: '<img src=x onerror=alert(1)> [S1] [S99]',
    drafts: [{ ...completed.drafts[0]!, title: "<script>Draft title</script>", description: "<b>Plain draft</b>", source_citations: ["S1", "S99"] }],
    sources: [{ ...completed.sources[0]!, title: "<script>Source title</script>", excerpt: "<iframe>Literal notes</iframe>", url: "javascript:alert(1)" }, { ...completed.sources[1]!, url: "https://other.example/private" }],
    steps: [{ tool: "search_project_sources", summary: "<img>Literal check summary</img>", result_count: 2 }],
  });
  await render(); await compose("Question"); await click("Ask project assistant");
  expect(container.querySelector(".assistant-answer")?.textContent).toContain("<img src=x onerror=alert(1)>");
  expect(container.querySelector(".assistant-draft")?.textContent).toContain("<script>Draft title</script>");
  expect(container.querySelector(".assistant-steps")?.textContent).toContain("<img>Literal check summary</img>");
  expect(container.querySelector("script, img, iframe, b")).toBeNull();
  expect(container.querySelectorAll(".assistant-source a")).toHaveLength(0);
  expect(container.querySelectorAll(".assistant-answer a")).toHaveLength(1);
  expect(container.querySelectorAll(".assistant-draft__references a")).toHaveLength(1);
});

it.each([
  ["model_unavailable", "The model service is unavailable"],
  ["invalid_response", "valid source references"],
  ["limit_reached", "reached its limit"],
] as const)("keeps valid sources and checks but withholds answers and drafts on %s", async (status, notice) => {
  configure();
  vi.mocked(assistantApi.run).mockResolvedValue({ ...completed, status, answer: "Do not show this answer", drafts: [{ ...completed.drafts[0]!, title: "Do not show this draft", description: "Unverified", source_citations: [] }], warnings: ["Review project evidence before continuing."] });
  await render(); await compose("Question"); await click("Ask project assistant");
  expect(container.textContent).toContain(notice);
  expect(container.textContent).toContain("Review project evidence before continuing.");
  expect(container.textContent).not.toContain("Do not show this answer");
  expect(container.textContent).not.toContain("Do not show this draft");
  expect(container.querySelector(".assistant-source")).not.toBeNull();
  expect(container.querySelector(".assistant-steps")).not.toBeNull();
});

it("reports missing project evidence without a fabricated response", async () => {
  configure();
  vi.mocked(assistantApi.run).mockResolvedValue({ ...completed, status: "no_evidence", answer: null, sources: [], drafts: [], steps: [] });
  await render(); await compose("Unknown requirement"); await click("Ask project assistant");
  expect(container.textContent).toContain("No matching project evidence");
  expect(container.querySelector(".assistant-answer")).toBeNull();
  expect(container.querySelector(".assistant-draft")).toBeNull();
});

it("retains the request for retry and clears a previous response when the next request fails", async () => {
  configure();
  vi.mocked(assistantApi.run).mockResolvedValueOnce(completed).mockRejectedValueOnce(new Error("Project sources changed. Please ask again."));
  await render(); await compose("Question"); await click("Ask project assistant");
  expect(container.querySelector(".assistant-draft")).not.toBeNull();
  await click("Ask project assistant");
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("Project sources changed");
  expect(container.querySelector(".assistant-results")).toBeNull();
  expect(container.querySelector("textarea")?.value).toBe("Question");
  expect(button("Ask project assistant").disabled).toBe(false);
});

it("blocks whitespace requests and duplicate submissions in the same render batch", async () => {
  configure(); const pending = deferred<AssistantResult>();
  vi.mocked(assistantApi.run).mockReturnValue(pending.promise);
  await render(); await compose("   ");
  expect(button("Ask project assistant").disabled).toBe(true);
  await compose("Question");
  await act(async () => {
    const form = container.querySelector("form")!;
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  expect(assistantApi.run).toHaveBeenCalledOnce();
  expect(button("Checking project information…").disabled).toBe(true);
  expect(container.querySelector("textarea")?.disabled).toBe(true);
  await act(async () => { pending.resolve(completed); });
  expect(button("Ask project assistant").disabled).toBe(false);
});

it("loads configuration before the form and lets the user retry settings errors", async () => {
  vi.mocked(assistantApi.settings).mockRejectedValueOnce(new Error("Project membership is required.")).mockResolvedValueOnce(settings);
  await render();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("Project membership is required");
  expect(container.querySelector("textarea")).toBeNull();
  await click("Try again");
  expect(button("Assistant unavailable")).toBeDefined();
  expect(assistantApi.settings).toHaveBeenCalledTimes(2);
});

it("ignores late project A availability after navigating to B", async () => {
  const old = deferred<AssistantSettings>();
  vi.mocked(assistantApi.settings).mockImplementation(project => project === "A" ? old.promise : Promise.resolve(settings));
  await render(); expect(container.querySelector("textarea")).toBeNull();
  await click("Open B");
  await act(async () => { old.resolve({ ...settings, available: true, notice: "Private A availability notice" }); });
  expect(container.textContent).not.toContain("Private A availability notice");
  expect(button("Assistant unavailable").disabled).toBe(true);
  expect(vi.mocked(assistantApi.settings).mock.calls[0]![1]?.aborted).toBe(true);
});

it("clears the previous project's request and ignores a delayed response after switching projects", async () => {
  configure(); const old = deferred<AssistantResult>();
  vi.mocked(assistantApi.run).mockReturnValue(old.promise);
  await render(); await compose("A private request"); await click("Ask project assistant"); await click("Open B");
  expect(container.querySelector("textarea")?.value).toBe("");
  await act(async () => { old.resolve({ ...completed, answer: "A private response [S1]" }); });
  expect(container.textContent).not.toContain("A private response");
  expect(container.querySelector(".assistant-draft")).toBeNull();
  expect(vi.mocked(assistantApi.run).mock.calls[0]![2]?.aborted).toBe(true);
});

it("isolates the current visit to A when an old request resolves after A → B → A", async () => {
  configure(); const old = deferred<AssistantResult>();
  vi.mocked(assistantApi.run).mockReturnValue(old.promise);
  await render(); await compose("Previous A request"); await click("Ask project assistant");
  await click("Open B"); await click("Open A"); await compose("Current A request");
  await act(async () => { old.resolve({ ...completed, question: "Previous A request" }); });
  expect(container.querySelector("textarea")?.value).toBe("Current A request");
  expect(container.textContent).not.toContain("Previous A request");
  expect(container.querySelector(".assistant-results")).toBeNull();
  expect(button("Ask project assistant").disabled).toBe(false);
});

it("lets the user review edits and creates a task only after explicit confirmation", async () => {
  await getDraft();
  await editDraft("  Final reviewed diagram  ", "Use the revised meeting decision.\nInclude the interface labels.");
  expect(assistantApi.createTask).not.toHaveBeenCalled();
  await click("Create task");
  expect(container.querySelector("dialog")?.textContent).toContain("Final reviewed diagram");
  expect(assistantApi.createTask).not.toHaveBeenCalled();
  await click("Confirm task creation");
  expect(assistantApi.createTask).toHaveBeenCalledWith("A", {
    approval_token: "signed-draft-token", title: "Final reviewed diagram", description: "Use the revised meeting decision.\nInclude the interface labels.",
  }, expect.any(AbortSignal));
  expect(container.querySelector(".assistant-draft__receipt")?.textContent).toContain("Task created in this project");
  expect(container.querySelector('a[href="/app/projects/A/tasks/created-task/"]')).not.toBeNull();
  expect(container.querySelector('[name="draft_title"]')).toBeNull();
  expect(container.querySelector(".assistant-saved")?.textContent).toBe("Task created");
  expect([...container.querySelectorAll("button")].some(row => row.textContent === "Create task")).toBe(false);
});

it("cancels task confirmation without saving the draft", async () => {
  await getDraft(); await click("Create task"); await click("Go back");
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 210)); });
  expect(container.querySelector("dialog")).toBeNull();
  expect(assistantApi.createTask).not.toHaveBeenCalled();
  expect(container.querySelector(".assistant-unsaved")).not.toBeNull();
});

it("blocks invalid edited titles and overlong descriptions before confirmation", async () => {
  await getDraft(); await editDraft("ab", "Short description");
  expect(button("Create task").disabled).toBe(true);
  await editDraft("Valid title", "x".repeat(2001));
  expect(button("Create task").disabled).toBe(true);
  await click("Create task");
  expect(container.querySelector("dialog")).toBeNull();
  expect(assistantApi.createTask).not.toHaveBeenCalled();
});

it("blocks duplicate confirmations and new assistant requests while a task is being created", async () => {
  const pending = deferred<AssistantCreatedTask>();
  vi.mocked(assistantApi.createTask).mockReturnValue(pending.promise);
  await getDraft(); await click("Create task");
  await act(async () => {
    const confirm = button("Confirm task creation");
    confirm.click(); confirm.click();
    container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  expect(assistantApi.createTask).toHaveBeenCalledOnce();
  expect(assistantApi.run).toHaveBeenCalledOnce();
  expect(button("Ask project assistant").disabled).toBe(true);
  expect(container.querySelector<HTMLInputElement>('[name="draft_title"]')?.disabled).toBe(true);
  await act(async () => { pending.resolve(createdTask); });
  expect(button("Ask project assistant").disabled).toBe(false);
});

it("retries the same confirmed token and payload after failure and handles an existing receipt", async () => {
  vi.mocked(assistantApi.createTask).mockRejectedValueOnce(new Error("Connection interrupted")).mockResolvedValueOnce({ ...createdTask, created: false });
  await getDraft(); await editDraft("Edited title", "Reviewed description"); await click("Create task"); await click("Confirm task creation");
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("Connection interrupted");
  expect(container.querySelector<HTMLInputElement>('[name="draft_title"]')?.disabled).toBe(true);
  await click("Retry create task");
  expect(assistantApi.createTask).toHaveBeenCalledOnce();
  await click("Confirm task creation");
  expect(assistantApi.createTask).toHaveBeenCalledTimes(2);
  expect(vi.mocked(assistantApi.createTask).mock.calls[1]![1]).toEqual(vi.mocked(assistantApi.createTask).mock.calls[0]![1]);
  expect(vi.mocked(assistantApi.createTask).mock.calls[1]![1].approval_token).toBe("signed-draft-token");
  expect(container.querySelector(".assistant-draft__receipt")?.textContent).toContain("No duplicate was added");
});

it("allows reviewed edits after a definite validation rejection without consuming the draft token", async () => {
  vi.mocked(assistantApi.createTask).mockRejectedValueOnce(new APIError(400, { error: {
    code: "validation_error", message: "A task with this title already exists.",
  } })).mockResolvedValueOnce(createdTask);
  await getDraft(); await click("Create task"); await click("Confirm task creation");
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("already exists");
  expect(container.querySelector<HTMLInputElement>('[name="draft_title"]')?.disabled).toBe(false);
  expect(container.querySelector<HTMLTextAreaElement>('[name="draft_description"]')?.disabled).toBe(false);
  await editDraft("Prepare the revised diagram", "Review the additional interface labels.");
  await click("Retry create task");
  expect(container.querySelector("dialog")?.textContent).toContain("Prepare the revised diagram");
  await click("Confirm task creation");
  expect(assistantApi.createTask).toHaveBeenCalledTimes(2);
  expect(vi.mocked(assistantApi.createTask).mock.calls[1]![1]).toEqual({
    approval_token: "signed-draft-token", title: "Prepare the revised diagram", description: "Review the additional interface labels.",
  });
  expect(container.querySelector(".assistant-draft__receipt")).not.toBeNull();
});

it("keeps an uncertain gateway timeout locked and retries the same confirmed payload", async () => {
  vi.mocked(assistantApi.createTask).mockRejectedValueOnce(new APIError(504, { error: {
    code: "request_failed", message: "The gateway timed out.",
  } })).mockResolvedValueOnce({ ...createdTask, created: false });
  await getDraft(); await editDraft("Confirmed diagram task", "Keep this exact description.");
  await click("Create task"); await click("Confirm task creation");
  expect(container.querySelector<HTMLInputElement>('[name="draft_title"]')?.disabled).toBe(true);
  expect(container.querySelector<HTMLTextAreaElement>('[name="draft_description"]')?.disabled).toBe(true);
  await click("Retry create task"); await click("Confirm task creation");
  expect(assistantApi.createTask).toHaveBeenCalledTimes(2);
  expect(vi.mocked(assistantApi.createTask).mock.calls[1]![1]).toEqual(vi.mocked(assistantApi.createTask).mock.calls[0]![1]);
  expect(container.querySelector(".assistant-draft__receipt")?.textContent).toContain("No duplicate was added");
});

it("tracks each confirmed draft separately and keeps new requests blocked until all creations finish", async () => {
  const first = deferred<AssistantCreatedTask>(), second = deferred<AssistantCreatedTask>();
  vi.mocked(assistantApi.run).mockResolvedValue({ ...completed, drafts: [completed.drafts[0]!, { ...completed.drafts[0]!, title: "Second task draft", approval_token: "second-signed-token" }] });
  vi.mocked(assistantApi.createTask).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  await getDraft(); await click("Create task"); await click("Confirm task creation");
  const secondCard = container.querySelectorAll(".assistant-draft")[1]!;
  await act(async () => { secondCard.querySelector<HTMLButtonElement>("button")!.click(); });
  await click("Confirm task creation");
  expect(vi.mocked(assistantApi.createTask).mock.calls.map(call => call[1].approval_token)).toEqual(["signed-draft-token", "second-signed-token"]);
  await act(async () => { first.resolve(createdTask); });
  expect(button("Ask project assistant").disabled).toBe(true);
  await act(async () => { second.resolve({ ...createdTask, task_id: "second-task", task_url: "/app/projects/A/tasks/second-task/", title: "Second task draft" }); });
  expect(button("Ask project assistant").disabled).toBe(false);
  expect(container.querySelectorAll(".assistant-draft__receipt")).toHaveLength(2);
});

it("keeps archived or otherwise ineligible drafts read-only without create controls", async () => {
  vi.mocked(assistantApi.run).mockResolvedValue({ ...completed, drafts: [{ ...completed.drafts[0]!, can_create: false, approval_token: "" }] });
  await getDraft();
  expect(container.textContent).toContain("Task creation is unavailable for this draft");
  expect(container.querySelector('[name="draft_title"]')).toBeNull();
  expect(container.querySelector('[name="draft_description"]')).toBeNull();
  expect([...container.querySelectorAll("button")].some(row => row.textContent === "Create task")).toBe(false);
  expect(assistantApi.createTask).not.toHaveBeenCalled();
});

it("shows at most five task drafts and never opens an external created-task URL", async () => {
  vi.mocked(assistantApi.run).mockResolvedValue({ ...completed, drafts: Array.from({ length: 6 }, (_, index) => ({ ...completed.drafts[0]!, title: `Draft number ${index}`, approval_token: `signed-token-${index}` })) });
  vi.mocked(assistantApi.createTask).mockResolvedValue({ ...createdTask, title: "<script>Unsafe returned title</script>", task_url: "https://other.example/task" });
  await getDraft();
  expect(container.querySelectorAll(".assistant-draft")).toHaveLength(5);
  expect(container.textContent).not.toContain("Draft number 5");
  await click("Create task"); await click("Confirm task creation");
  expect(container.querySelector(".assistant-draft__receipt a")).toBeNull();
  expect(container.querySelector("script")).toBeNull();
});

it("does not link a created-task receipt to another project's task", async () => {
  vi.mocked(assistantApi.createTask).mockResolvedValue({ ...createdTask, task_url: "/app/projects/B/tasks/created-task/" });
  await getDraft(); await click("Create task"); await click("Confirm task creation");
  expect(container.querySelector(".assistant-draft__receipt a")).toBeNull();
});

it("ignores a delayed task receipt after navigating away and returning to the same project", async () => {
  const old = deferred<AssistantCreatedTask>();
  vi.mocked(assistantApi.createTask).mockReturnValue(old.promise);
  await getDraft(); await click("Create task"); await click("Confirm task creation");
  await click("Open B"); await click("Open A"); await compose("Current A request");
  await act(async () => { old.resolve({ ...createdTask, title: "Previous A created task" }); });
  expect(container.textContent).not.toContain("Previous A created task");
  expect(container.querySelector(".assistant-draft__receipt")).toBeNull();
  expect(container.querySelector<HTMLTextAreaElement>('[name="question"]')?.value).toBe("Current A request");
  expect(button("Ask project assistant").disabled).toBe(false);
  expect(vi.mocked(assistantApi.createTask).mock.calls[0]![2]?.aborted).toBe(true);
});
