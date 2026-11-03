import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import CampusPage from "./CampusPage";
import { campusApi } from "../api/campus";
import { projectApi } from "../api/resources";
import { openCreation } from "../../tests/dialogs";

vi.mock("../api/campus", () => ({ campusApi: { overview: vi.fn(), todos: vi.fn(), action: vi.fn(), search: vi.fn() } }));
vi.mock("../api/resources", () => ({ projectApi: { listAll: vi.fn() } }));
let root: Root, container: HTMLDivElement, client: QueryClient;
const empty = { terms: [], courses: [], links: [], templates: [], join_requests: [] };
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); vi.clearAllMocks();
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false }, mutations: { retry: false } } });
  client.setQueryData(["campus"], empty); client.setQueryData(["projects", "all"], { results: [] });
  client.setQueryData(["campus-todos", "open", "", 1], { results: [], page: 1, pages: 1, total: 0 });
  vi.mocked(campusApi.overview).mockResolvedValue(empty); vi.mocked(campusApi.action).mockResolvedValue({});
  vi.mocked(projectApi.listAll).mockResolvedValue({ results: [], count: 0, next: null, previous: null });
  vi.mocked(campusApi.todos).mockResolvedValue({ results: [], total: 0, page: 1, pages: 1, page_size: 25 });
});
afterEach(async () => { await act(async () => root.unmount()); client.clear(); container.remove(); });
async function render() {
  await act(async () => root.render(<QueryClientProvider client={client}><MemoryRouter><CampusPage /></MemoryRouter></QueryClientProvider>));
}
async function submit() {
  await act(async () => {
    document.body.querySelector("dialog form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await new Promise(resolve => setTimeout(resolve, 25));
  });
}

it.each([
  { trigger: "Add term", path: "terms/", fields: { university: "University", year: "2027", name: "Semester 1" }, expected: { university: "University", year: 2027, name: "Semester 1" } },
  { trigger: "Add course", path: "courses/", fields: { university: "University", code: "COMP1001", name: "Computing" }, expected: { university: "University", code: "COMP1001", name: "Computing" } },
])("creates $trigger through its modal with the entered values", async ({ trigger, path, fields, expected }) => {
  await render(); expect(document.body.querySelector('[name="university"]')).toBeNull();
  await openCreation(trigger);
  for (const [name, value] of Object.entries(fields)) document.body.querySelector<HTMLInputElement>(`dialog [name="${name}"]`)!.value = value!;
  await submit();
  expect(campusApi.action).toHaveBeenCalledWith(path, expected);
  expect(document.body.querySelector("dialog")).toBeNull(); expect(document.body.textContent).toContain("Saved.");
});

it("keeps a rejected course editable and closes only after a successful retry", async () => {
  vi.mocked(campusApi.action).mockRejectedValueOnce(new Error("This course already exists."));
  await render(); await openCreation("Add course");
  const input = document.body.querySelector<HTMLInputElement>('dialog [name="name"]')!;
  input.value = "Preserve my course"; await submit();
  expect(input.isConnected).toBe(true); expect(input.value).toBe("Preserve my course");
  expect(document.body.querySelector("dialog")?.textContent).toContain("already exists");
  await submit(); expect(campusApi.action).toHaveBeenCalledTimes(2); expect(document.body.querySelector("dialog")).toBeNull();
});
