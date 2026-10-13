import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { knowledgeApi, type KnowledgeAnswer, type KnowledgeSearch, type KnowledgeSettings } from "../api/knowledge";
import ProjectKnowledgePage from "./ProjectKnowledgePage";

vi.mock("../api/knowledge", () => ({ knowledgeApi: { settings: vi.fn(), search: vi.fn(), ask: vi.fn() } }));

const settings: KnowledgeSettings = {
  generation_available: false, provider: "disabled", source_types: ["file", "meeting"],
  supported_files: ["txt", "csv", "pdf", "docx"], max_question_length: 1000,
  retrieval: "bm25", notice: "Project documents and meeting notes are searched privately.",
};
const sources: KnowledgeSearch = {
  question: "What is required?", warnings: [], limited: false, retrieval: "bm25",
  sources: [{ citation: "S1", kind: "file", source_id: "brief", title: "Assignment brief", version: 2, page: 3,
    excerpt: "The final report must include the design rationale.", url: "/api/v1/files/projects/A/documents/brief/download/?version=2", locator: "Paragraph 4" }],
};
const generated: KnowledgeAnswer = { ...sources, status: "answered", answer: "Include the design rationale. [S1]", model: "configured-model" };

function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function Navigation() {
  const navigate = useNavigate();
  return <><button onClick={() => navigate("/projects/A/knowledge")}>Open A</button><button onClick={() => navigate("/projects/B/knowledge")}>Open B</button></>;
}
let root: Root, container: HTMLDivElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.resetAllMocks();
  vi.mocked(knowledgeApi.settings).mockResolvedValue(settings);
  vi.mocked(knowledgeApi.search).mockResolvedValue(sources);
  vi.mocked(knowledgeApi.ask).mockResolvedValue(generated);
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
async function render() {
  await act(async () => root.render(<MemoryRouter initialEntries={["/projects/A/knowledge"]}><Navigation /><Routes><Route path="/projects/:projectId/knowledge" element={<ProjectKnowledgePage />} /></Routes></MemoryRouter>));
}
function button(name: string) {
  const element = [...container.querySelectorAll<HTMLButtonElement>("button")].find(row => row.textContent === name);
  expect(element, `Missing button ${name}`).toBeDefined(); return element!;
}
async function click(name: string) { await act(async () => { button(name).click(); }); }
async function compose(value: string) {
  const textarea = container.querySelector("textarea")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(textarea, value);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

it("searches without invoking a model when generation is disabled and shows original evidence", async () => {
  const localWrites = vi.spyOn(Storage.prototype, "setItem");
  try {
    await render();
    expect(container.textContent).toContain("Answer generation is not configured");
    expect(button("Search project sources").disabled).toBe(true);
    await compose("  What is required?  "); await click("Search project sources");
    expect(knowledgeApi.search).toHaveBeenCalledWith("A", { question: "What is required?", max_sources: 5 }, expect.any(AbortSignal));
    expect(knowledgeApi.ask).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Version 2 · Page 3 · Paragraph 4");
    expect(container.querySelector("blockquote")?.textContent).toContain("design rationale");
    expect(container.querySelector<HTMLAnchorElement>(".knowledge-source__open")?.getAttribute("href")).toContain("version=2");
    expect(container.querySelector(".knowledge-answer")).toBeNull();
    expect(localWrites).not.toHaveBeenCalled();
  } finally { localWrites.mockRestore(); }
});

it("generates a cited answer when configured and also offers source-only search", async () => {
  vi.mocked(knowledgeApi.settings).mockResolvedValue({ ...settings, generation_available: true, provider: "compatible" });
  await render(); await compose("What is required?"); await click("Ask project question");
  expect(knowledgeApi.ask).toHaveBeenCalledWith("A", { question: "What is required?", max_sources: 5 }, expect.any(AbortSignal));
  expect(container.querySelector(".knowledge-answer")?.textContent).toBe(generated.answer);
  expect(container.querySelector<HTMLAnchorElement>('.knowledge-answer a')?.getAttribute("href")).toBe("#knowledge-source-S1");
  expect(container.querySelector("#knowledge-source-S1")).not.toBeNull();
  await click("Search sources only");
  expect(knowledgeApi.search).toHaveBeenCalledOnce();
  expect(container.querySelector(".knowledge-answer")).toBeNull();
});

it("shows source type, version and page once when the locator repeats their metadata", async () => {
  vi.mocked(knowledgeApi.search).mockResolvedValue({ ...sources, sources: [
    { ...sources.sources[0]!, version: 1, page: null, locator: "Version 1" },
    { ...sources.sources[0]!, citation: "S2", locator: "Version 2, page 3" },
    { ...sources.sources[0]!, citation: "S3", kind: "meeting", version: 1, page: null, locator: "Meeting notes, version 1" },
  ] });
  await render(); await compose("Question"); await click("Search project sources");
  expect([...container.querySelectorAll(".knowledge-source__location")].map(row => row.textContent)).toEqual([
    "Project file · Version 1", "Project file · Version 2 · Page 3", "Meeting notes · Version 1",
  ]);
});

it("renders model and source markup as literal text and rejects unsafe or external source links", async () => {
  vi.mocked(knowledgeApi.settings).mockResolvedValue({ ...settings, generation_available: true, provider: "ollama" });
  vi.mocked(knowledgeApi.ask).mockResolvedValue({ ...generated, answer: '<img src=x onerror=alert(1)> [S1] [S99]', sources: [
    { ...sources.sources[0]!, title: "<script>secret</script>", excerpt: "<b>Literal notes</b>", url: "javascript:alert(1)" },
    { ...sources.sources[0]!, citation: "S2", title: "External", url: "https://other.example/private" },
  ] });
  await render(); await compose("Question"); await click("Ask project question");
  expect(container.querySelector(".knowledge-answer")?.textContent).toContain("<img src=x onerror=alert(1)>");
  expect(container.querySelector("blockquote")?.textContent).toBe("<b>Literal notes</b>");
  expect(container.querySelector("script, img, iframe, b")).toBeNull();
  expect(container.querySelectorAll(".knowledge-source a")).toHaveLength(0);
  expect(container.querySelectorAll(".knowledge-answer a")).toHaveLength(1);
});

it("reports no evidence and partial searches without inventing an answer", async () => {
  vi.mocked(knowledgeApi.search).mockResolvedValue({ ...sources, sources: [], limited: true, warnings: ["Scanned PDF could not be read."] });
  await render(); await compose("Unknown requirement"); await click("Search project sources");
  expect(container.textContent).toContain("No matching project sources");
  expect(container.textContent).toContain("Only part of this project's material was searched");
  expect(container.textContent).toContain("Scanned PDF could not be read.");
  expect(container.querySelector(".knowledge-answer")).toBeNull();
});

it("withholds an unverified answer and retains source excerpts when a configured model fails", async () => {
  vi.mocked(knowledgeApi.settings).mockResolvedValue({ ...settings, generation_available: true, provider: "compatible" });
  vi.mocked(knowledgeApi.ask).mockResolvedValueOnce({ ...generated, status: "unverified_answer", answer: "Do not display this answer." })
    .mockResolvedValueOnce({ ...generated, status: "model_unavailable", answer: null });
  await render(); await compose("Question"); await click("Ask project question");
  expect(container.textContent).toContain("was withheld");
  expect(container.textContent).not.toContain("Do not display this answer");
  expect(container.querySelector("blockquote")?.textContent).toContain("design rationale");
  await click("Ask project question");
  expect(container.textContent).toContain("An answer could not be generated");
  expect(container.querySelector("blockquote")?.textContent).toContain("design rationale");
});

it("keeps the question for retry and clears previous results after a request error", async () => {
  vi.mocked(knowledgeApi.search).mockResolvedValueOnce(sources).mockRejectedValueOnce(new Error("Project sources changed while answering. Please ask again."));
  await render(); await compose("Question"); await click("Search project sources");
  expect(container.querySelector("blockquote")).not.toBeNull();
  await click("Search project sources");
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("Project sources changed");
  expect(container.querySelector("blockquote")).toBeNull();
  expect(container.querySelector("textarea")?.value).toBe("Question");
  expect(button("Search project sources").disabled).toBe(false);
});

it("blocks duplicate submissions while searching and rejects whitespace questions", async () => {
  const pending = deferred<KnowledgeSearch>();
  vi.mocked(knowledgeApi.search).mockReturnValue(pending.promise);
  await render(); await compose("   ");
  expect(button("Search project sources").disabled).toBe(true);
  await compose("Question");
  await act(async () => {
    const form = container.querySelector("form")!;
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  expect(button("Searching sources…").disabled).toBe(true);
  expect(container.querySelector("textarea")?.disabled).toBe(true);
  await act(async () => { container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
  expect(knowledgeApi.search).toHaveBeenCalledOnce();
  await act(async () => { pending.resolve(sources); });
  expect(button("Search project sources").disabled).toBe(false);
});

it("loads project settings before offering search and retries a settings error", async () => {
  vi.mocked(knowledgeApi.settings).mockRejectedValueOnce(new Error("Project membership is required.")).mockResolvedValueOnce(settings);
  await render();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("Project membership is required");
  expect(container.querySelector("textarea")).toBeNull();
  await click("Try again");
  expect(container.querySelector("textarea")).not.toBeNull();
  expect(knowledgeApi.settings).toHaveBeenCalledTimes(2);
});

it("ignores late project A settings after navigating to B", async () => {
  const old = deferred<KnowledgeSettings>();
  vi.mocked(knowledgeApi.settings).mockImplementation(project => project === "A" ? old.promise : Promise.resolve(settings));
  await render();
  expect(container.querySelector("textarea")).toBeNull();
  await click("Open B");
  await act(async () => { old.resolve({ ...settings, notice: "A private settings notice", generation_available: true }); });
  expect(container.textContent).not.toContain("A private settings notice");
  expect(button("Search project sources")).toBeDefined();
  expect(vi.mocked(knowledgeApi.settings).mock.calls[0]![1]?.aborted).toBe(true);
});

it("aborts and ignores a late answer after switching projects and clears the previous question", async () => {
  const old = deferred<KnowledgeAnswer>();
  vi.mocked(knowledgeApi.settings).mockResolvedValue({ ...settings, generation_available: true, provider: "compatible" });
  vi.mocked(knowledgeApi.ask).mockReturnValue(old.promise);
  await render(); await compose("A private question"); await click("Ask project question"); await click("Open B");
  expect(container.querySelector("textarea")?.value).toBe("");
  await act(async () => { old.resolve({ ...generated, answer: "A private answer [S1]" }); });
  expect(container.textContent).not.toContain("A private answer");
  expect(container.querySelector(".knowledge-results")).toBeNull();
  expect(vi.mocked(knowledgeApi.ask).mock.calls[0]![2]?.aborted).toBe(true);
});

it("isolates a previous visit to A when a pending source search resolves after A → B → A", async () => {
  const old = deferred<KnowledgeSearch>();
  vi.mocked(knowledgeApi.search).mockReturnValue(old.promise);
  await render(); await compose("Previous A question"); await click("Search project sources");
  await click("Open B"); await click("Open A"); await compose("Current A question");
  await act(async () => { old.resolve({ ...sources, question: "Previous A question" }); });
  expect(container.querySelector("textarea")?.value).toBe("Current A question");
  expect(container.textContent).not.toContain("Previous A question");
  expect(container.querySelector(".knowledge-results")).toBeNull();
  expect(button("Search project sources").disabled).toBe(false);
});
