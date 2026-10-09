import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import TeamFinderPage from "./TeamFinderPage";
import { recruitingApi, type RecruitingRecommendations } from "../api/recruiting";
import { APIError } from "../api/client";

vi.mock("../api/recruiting", () => ({ recruitingApi: Object.fromEntries(["recommendations", "list", "overview", "detail", "create", "update", "listingAction", "applications", "decide", "withdraw", "reports", "resolveReport"].map(name => [name, vi.fn()])) }));
vi.mock("../api/resources", () => ({ accountApi: { me: vi.fn() } }));

let container: HTMLDivElement, root: Root, cache: QueryClient;
const listing = { id: "suggestion", title: "Matching study team", university: "Example University", course: "COMP1001", term: "Semester 2", description: "Opening details", skills: ["Python"], languages: ["English"], cooperation: "hybrid", capacity: 2, remaining: 1, expires_at: "2026-11-01T00:00:00Z", status: "open", owner: { id: "publisher", display_name: "Publisher" }, student_status: "self_reported" as const, bookmarked: false, is_owner: false, my_application: null, updated_at: "2026-10-02T01:00:00Z" };
const matching: RecruitingRecommendations = { results: [{ ...listing, match_reasons: [{ kind: "skills", values: ["Python"], text: "Skills in common: Python." }] }], count: 1, page: 1, pages: 1, preferences: { courses: [], skills: ["Python"], languages: ["English"], cooperation: "online", overrides: [], missing_fields: ["course"] }, examined_count: 1, eligible_count: 1, candidate_window: 200, limited: false, ordering: "Course, then skills, language and working style; newest first for ties." };

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.clearAllMocks();
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  cache = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
  cache.setQueryData(["me"], { user: { id: "student" }, permissions: { site_moderator: false } });
  const overview = { managed_projects: [], mine: [], applications: [], mine_pagination: { count: 0, page: 1, pages: 1 }, applications_pagination: { count: 0, page: 1, pages: 1 }, projects_pagination: { count: 0, page: 1, pages: 1 } };
  const empty = { results: [], count: 0, page: 1, pages: 1 };
  cache.setQueryData(["recruiting-overview", 1, 1, 1], overview);
  cache.setQueryData(["recruiting-listings", {}, 1], empty);
  vi.mocked(recruitingApi.overview).mockResolvedValue(overview);
  vi.mocked(recruitingApi.list).mockResolvedValue(empty);
  vi.mocked(recruitingApi.recommendations).mockResolvedValue(matching);
});
afterEach(async () => { await act(async () => root.unmount()); cache.clear(); container.remove(); });
async function render() { await act(async () => root.render(<QueryClientProvider client={cache}><MemoryRouter><TeamFinderPage /></MemoryRouter></QueryClientProvider>)); }
async function click(label: string) { const button = [...container.querySelectorAll("button")].find(value => value.textContent === label); if (!button) throw new Error("Missing button: " + label); await act(async () => { button.click(); }); }
async function submit(form: HTMLFormElement) { await act(async () => { form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); }); }
async function waitForContent(text: string) {
  await vi.waitFor(async () => {
    // Flush the query observer's scheduled notification inside React's act.
    await act(async () => { await new Promise<void>(resolve => setTimeout(resolve, 0)); });
    expect(container.textContent).toContain(text);
  });
}

function heading(text: string) {
  return [...container.querySelectorAll<HTMLHeadingElement>("h3")].find(value => value.textContent === text)!;
}

function addManagedProject() {
  cache.setQueryData(["recruiting-overview", 1, 1, 1], {
    managed_projects: [{ id: "project", name: "Private study project" }], mine: [], applications: [],
    mine_pagination: { count: 0, page: 1, pages: 1 },
    applications_pagination: { count: 0, page: 1, pages: 1 },
    projects_pagination: { count: 1, page: 1, pages: 1 },
  });
}

it("reveals the selected opening after loading and when the same opening is viewed again", async () => {
  cache.setQueryData(["recruiting-listings", {}, 1], { results: [listing], count: 1, page: 1, pages: 1 });
  let resolveDetail!: (value: typeof listing) => void;
  vi.mocked(recruitingApi.detail).mockReturnValue(new Promise(resolve => { resolveDetail = resolve; }));
  await render();
  await click("View opening");
  expect(document.activeElement).not.toBe(heading("Opening details"));
  const scroll = vi.fn();
  heading("Opening details").scrollIntoView = scroll;
  await act(async () => resolveDetail(listing));
  await waitForContent("Apply to join team");
  expect(document.activeElement).toBe(heading("Opening details"));
  expect(scroll).toHaveBeenCalledWith({ block: "start", behavior: "instant" });
  const opener = [...container.querySelectorAll("button")].find(value => value.textContent === "View opening")!;
  opener.focus();
  await click("View opening");
  expect(document.activeElement).toBe(heading("Opening details"));
  expect(scroll).toHaveBeenCalledTimes(2);
});

it("reveals the publishing form without publishing or changing project data", async () => {
  addManagedProject();
  await render();
  await click("Publish a team opening");
  expect(document.activeElement).toBe(heading("Publish an opening"));
  expect(container.querySelector<HTMLSelectElement>('[name="project"]')?.disabled).toBe(false);
  expect(recruitingApi.create).not.toHaveBeenCalled();
  expect(recruitingApi.update).not.toHaveBeenCalled();
});

it("moves focus from opening details to the populated edit form", async () => {
  addManagedProject();
  cache.setQueryData(["recruiting-listings", {}, 1], { results: [listing], count: 1, page: 1, pages: 1 });
  vi.mocked(recruitingApi.detail).mockResolvedValue({ ...listing, project: "project", is_owner: true });
  vi.mocked(recruitingApi.applications).mockResolvedValue({ results: [], count: 0, page: 1, pages: 1 });
  await render();
  await click("View opening");
  await waitForContent("Edit opening");
  await click("Edit opening");
  expect(document.activeElement).toBe(heading("Edit team opening"));
  expect(container.querySelector<HTMLInputElement>('[name="title"]')?.value).toBe(listing.title);
  expect(container.querySelector<HTMLSelectElement>('[name="project"]')?.disabled).toBe(true);
  expect(recruitingApi.update).not.toHaveBeenCalled();
});

it("loads suggestions on demand with factual explanations and keeps joining explicit", async () => {
  await render(); expect(recruitingApi.recommendations).not.toHaveBeenCalled();
  await click("Show suggestions");
  await waitForContent("Skills in common: Python.");
  expect(recruitingApi.recommendations).toHaveBeenCalledWith({}, 1);
  expect(container.textContent).toContain("Skills in common: Python.");
  expect(container.textContent).toContain("Joining still requires an application and approval.");
  expect(container.textContent).not.toContain("score");
  expect(recruitingApi.listingAction).not.toHaveBeenCalled();
  vi.mocked(recruitingApi.detail).mockResolvedValue(listing);
  await click("View suggested opening");
  await waitForContent("Apply to join team");
  expect(recruitingApi.detail).toHaveBeenCalledWith("suggestion");
  expect(container.textContent).toContain("Apply to join team");
  expect(recruitingApi.decide).not.toHaveBeenCalled();
});

it("uses temporary course and skill preferences without writing a profile or application", async () => {
  await render(); await click("Show suggestions");
  const form = container.querySelector<HTMLInputElement>('[placeholder="Use my courses"]')!.closest("form")!;
  form.querySelector<HTMLInputElement>('[name="course"]')!.value = "  COMP1001 ";
  form.querySelector<HTMLInputElement>('[name="skill"]')!.value = "中文写作";
  form.querySelector<HTMLSelectElement>('[name="cooperation"]')!.value = "campus";
  await submit(form);
  await waitForContent("Preferences here do not change your profile.");
  expect(recruitingApi.recommendations).toHaveBeenLastCalledWith({ course: "COMP1001", university: "", skill: "中文写作", language: "", cooperation: "campus" }, 1);
  expect(container.textContent).toContain("Preferences here do not change your profile.");
  expect(recruitingApi.listingAction).not.toHaveBeenCalled();
  await click("Use my profile");
  expect(recruitingApi.recommendations).toHaveBeenLastCalledWith({}, 1);
});

it("handles incomplete profiles and bounded discovery without inventing matches", async () => {
  vi.mocked(recruitingApi.recommendations).mockResolvedValue({ ...matching, results: [], count: 0, limited: true, examined_count: 200, eligible_count: 250, preferences: { courses: [], skills: [], languages: [], cooperation: "", overrides: [], missing_fields: ["course", "skills", "languages", "working style"] } });
  await render(); await click("Show suggestions");
  await waitForContent("No matching suggestions yet");
  expect(container.textContent).toContain("No matching suggestions yet");
  expect(container.textContent).toContain("200 most recent eligible openings");
  expect(container.querySelector<HTMLAnchorElement>('[href="/app/profile"]')?.textContent).toBe("Edit your profile");
  expect(container.textContent).not.toContain("Matching study team");
});

it("keeps discovery usable when suggestion loading fails and permits retry", async () => {
  vi.mocked(recruitingApi.recommendations).mockRejectedValueOnce(new APIError(503, { error: { message: "Suggestions unavailable" } }));
  await render(); await click("Show suggestions");
  await waitForContent("Suggestions unavailable");
  expect(container.textContent).toContain("Suggestions unavailable");
  expect(container.textContent).toContain("Find teams");
  await click("Refresh suggestions");
  await waitForContent("Skills in common: Python.");
  expect(container.textContent).toContain("Skills in common: Python.");
});
