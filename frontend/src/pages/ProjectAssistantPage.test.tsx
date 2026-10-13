import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { assistantApi, type AssistantResult, type AssistantSettings } from "../api/assistant";
import ProjectAssistantPage from "./ProjectAssistantPage";

vi.mock("../api/assistant", () => ({ assistantApi: { settings: vi.fn(), run: vi.fn() } }));
const settings: AssistantSettings = { available: false, notice: "The assistant needs a model that supports tools.", tools: ["search_project_sources", "list_project_tasks", "propose_tasks"], max_question_length: 1000, max_steps: 4 };
const completed: AssistantResult = {
  question: "What should we work on next?", status: "completed", answer: "Prepare the final diagram [S1], after checking the existing review task [S2].", model: "configured-model", warnings: [],
  sources: [
    { citation: "S1", kind: "meeting", source_id: "notes", title: "Design review", version: 2, page: null, excerpt: "Prepare a final design diagram.", url: "/app/projects/A/coordination/?meeting=meeting-a", locator: "Meeting notes, version 2" },
    { citation: "S2", kind: "task", source_id: "task-a", title: "Review the design", version: null, page: null, excerpt: "Status: in progress. Review the proposed design.", url: "/app/projects/A/tasks/task-a/", locator: "Current task" },
  ],
  drafts: [{ title: "Prepare final diagram", description: "Create a diagram based on the meeting decision.", source_citations: ["S1"] }],
  steps: [
    { tool: "search_project_sources", summary: "Found the design review notes.", result_count: 1 },
    { tool: "list_project_tasks", summary: "Checked the existing design review task.", result_count: 1 },
    { tool: "propose_tasks", summary: "Prepared one suggested task.", result_count: 1 },
  ],
};

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

it("clearly disables an unconfigured assistant and directs the user to Knowledge without fake output", async () => {
  await render();
  expect(container.textContent).toContain("The assistant needs a configured model service");
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
    expect(container.querySelector(".assistant-draft__description")?.textContent).toBe(completed.drafts[0]!.description);
    expect(container.querySelector<HTMLAnchorElement>(".assistant-draft__references a")?.getAttribute("href")).toBe("#assistant-source-S1");
    expect(container.querySelector(".assistant-steps")?.textContent).toContain("Checked project tasks");
    expect(container.querySelector(".assistant-steps")?.textContent).toContain("Prepared task drafts");
    expect(container.querySelector('[name="title"]')).toBeNull();
    expect(container.textContent).not.toContain("Create task");
    expect(storage).not.toHaveBeenCalled();
  } finally { storage.mockRestore(); }
});

it("renders answer, draft, tool and source markup literally and blocks unsafe or external links", async () => {
  configure();
  vi.mocked(assistantApi.run).mockResolvedValue({ ...completed,
    answer: '<img src=x onerror=alert(1)> [S1] [S99]',
    drafts: [{ title: "<script>Draft title</script>", description: "<b>Plain draft</b>", source_citations: ["S1", "S99"] }],
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
  vi.mocked(assistantApi.run).mockResolvedValue({ ...completed, status, answer: "Do not show this answer", drafts: [{ title: "Do not show this draft", description: "Unverified", source_citations: [] }], warnings: ["Review project evidence before continuing."] });
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
