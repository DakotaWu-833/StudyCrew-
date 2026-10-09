import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { campusApi, type CampusOverview, type ProjectPlan } from "../api/campus";
import ProjectPlanPage from "./ProjectPlanPage";
import ResourcesPage from "./ResourcesPage";

vi.mock("../api/campus", () => ({ campusApi: { plan: vi.fn(), overview: vi.fn(), joins: vi.fn(), resources: vi.fn(), projectAction: vi.fn() } }));

const overview: CampusOverview = { terms: [], courses: [], links: [], templates: [], join_requests: [] };
const plan: ProjectPlan = {
  project: { id: "project-a", name: "Private team", archived_at: null, role: "member" }, current_user: "member",
  members: [{ id: "member", display_name: "Morgan", role: "member" }, { id: "owner", display_name: "Alex", role: "owner" }],
  tasks: [], milestones: [], course_links: [], agreement: { body: "Discuss blockers each week.", revision: 3, confirmations: [] }, submission: null,
  task_choices: [], task_pagination: { total: 0, page: 1, pages: 1, page_size: 50 },
};

describe("academic pages support real member actions", () => {
  let container: HTMLDivElement;
  let root: Root;
  let client: QueryClient;
  beforeEach(() => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    vi.clearAllMocks();
    container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
    client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
    client.setQueryData(["project-plan", "project-a"], plan); client.setQueryData(["project-plan", "project-a", 1], plan); client.setQueryData(["campus"], overview);
    vi.mocked(campusApi.plan).mockResolvedValue(plan); vi.mocked(campusApi.overview).mockResolvedValue(overview);
    vi.mocked(campusApi.projectAction).mockResolvedValue({});
  });
  afterEach(async () => { await act(async () => root.unmount()); client.clear(); container.remove(); vi.restoreAllMocks(); });
  const render = async (page: "plan" | "resources") => {
    await act(async () => root.render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[`/projects/project-a/${page}`]}><Routes><Route path="/projects/:projectId/plan" element={<ProjectPlanPage />} /><Route path="/projects/:projectId/resources" element={<ResourcesPage />} /></Routes></MemoryRouter></QueryClientProvider>));
  };
  const settle = async () => { await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); }); };

  it("lets a member confirm the displayed agreement revision without owner controls", async () => {
    await render("plan");
    expect(container.textContent).toContain("Revision 3");
    expect(container.textContent).not.toContain("Start from an assignment template");
    expect(container.textContent).not.toContain("Create private join link");
    const button = [...container.querySelectorAll<HTMLButtonElement>("button")].find((item) => item.textContent === "Confirm this agreement")!;
    await act(async () => button.click()); await settle();
    expect(campusApi.projectAction).toHaveBeenCalledWith("project-a", "agreement/confirm/", { revision: 3 }, "POST");
  });

  it("adds a resource with actual form values and opens provider links safely", async () => {
    const resource = { id: "resource-a", project: "project-a", project_name: "Private team", title: "Assignment brief", url: "https://example.com/brief", description: "", tags: ["brief"], pinned: true, added_by: { id: "owner", display_name: "Alex" }, can_edit: false, created_at: "2026-10-01T00:00:00Z" };
    const page = { results: [resource], total: 1, page: 1, pages: 1, page_size: 25 };
    client.setQueryData(["resources", "project-a", "", "", 1], page);
    vi.mocked(campusApi.resources).mockResolvedValue(page);
    await render("resources");
    const link = container.querySelector<HTMLAnchorElement>('a[href="https://example.com/brief"]')!;
    expect(link.rel).toContain("noreferrer"); expect(link.target).toBe("_blank");
    expect([...container.querySelectorAll("button")].some((button) => button.textContent === "Edit")).toBe(false);
    const form = container.querySelector<HTMLFormElement>("form")!;
    form.querySelector<HTMLInputElement>('[name="title"]')!.value = "Team notes";
    form.querySelector<HTMLInputElement>('[name="url"]')!.value = "https://example.com/notes";
    form.querySelector<HTMLInputElement>('[name="tags"]')!.value = "notes, research";
    await act(async () => form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))); await settle();
    expect(campusApi.projectAction).toHaveBeenCalledWith("project-a", "resources/", { title: "Team notes", url: "https://example.com/notes", description: "", tags: ["notes", "research"], pinned: false }, "POST");
  });
});
