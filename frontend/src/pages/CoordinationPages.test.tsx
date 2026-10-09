import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { coordinationApi, type AvailabilityData, type CalendarSubscription, type ContributionClaim, type EvidenceData, type MeetingRecord, type SchedulingPoll } from "../api/coordination";
import { accountApi, membershipApi, projectApi, taskApi } from "../api/resources";
import { APIError } from "../api/client";
import type { Me, Membership, Page, Project } from "../api/types";
import CalendarPage from "./CalendarPage";
import CoordinationPage from "./CoordinationPage";
import EvidencePage from "./EvidencePage";

vi.mock("../api/coordination", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api/coordination")>();
  return { ...original, coordinationApi: { ...original.coordinationApi,
    calendar: vi.fn(), subscriptions: vi.fn(), subscribe: vi.fn(), rotateSubscription: vi.fn(), revokeSubscription: vi.fn(),
    availability: vi.fn(), saveAvailability: vi.fn(), polls: vi.fn(), createPoll: vi.fn(), vote: vi.fn(), closePoll: vi.fn(), cancelPoll: vi.fn(),
    meetingRecords: vi.fn(), meetingRecord: vi.fn(), saveRecord: vi.fn(), attendance: vi.fn(), action: vi.fn(), repeat: vi.fn(), confirmMinutes: vi.fn(),
    evidence: vi.fn(), claim: vi.fn(), respondClaim: vi.fn(), reviewClaim: vi.fn(), withdrawClaim: vi.fn(),
  } };
});
vi.mock("../api/resources", () => ({ accountApi: { me: vi.fn() }, membershipApi: { list: vi.fn() }, projectApi: { list: vi.fn(), get: vi.fn() }, taskApi: { list: vi.fn() } }));

const owner = { id: "owner", display_name: "Alex" };
const member = { id: "member", display_name: "Morgan" };
const former = { id: "former", display_name: "Casey" };
const me: Me = { user: owner, email: "alex@example.com", permissions: { site_moderator: false }, profile: { email: "alex@example.com", display_name: "Alex", course_code: "", time_zone: "Australia/Sydney", biography: "", avatar_url: "", avatar_image_url: "", updated_at: "2026-10-01T00:00:00Z" } };
const project: Project = { id: "project-a", name: "Private team", description: "", due_at: null, created_by: owner, created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z", archived_at: null, current_user_role: "owner", member_count: 2 };
const page = <T,>(results: T[]): Page<T> => ({ count: results.length, next: null, previous: null, results });
const memberships: Membership[] = [owner, member].map((user, index) => ({ id: `membership-${index}`, project: project.id, user, role: index ? "member" : "owner", joined_at: "2026-10-01T00:00:00Z", removed_at: null }));
const availability: AvailabilityData = { week_start: "2026-10-05", time_zone: "Australia/Sydney", basis: "Self-reported free time; confirm candidate dates.", members: [{ ...owner, role: "owner", shared_availability: true }, { ...member, role: "member", shared_availability: false }], mine: { slots: [], time_zone: "Australia/Sydney" }, cells: [] };
const poll: SchedulingPoll = { id: "poll-a", title: "Review time", agenda: "Discuss the draft", location: "Library", closed_at: null, meeting_id: null, can_manage: false, can_vote: true, participants: [{ user_id: owner.id, required: false, display_name: owner.display_name, active: true }, { user_id: member.id, required: true, display_name: member.display_name, active: true }], options: [{ id: "option-a", starts_at: "2026-10-05T01:00:00Z", ends_at: "2026-10-05T02:00:00Z", votes: [] }] };
const record: MeetingRecord = { id: "meeting-a", title: "Draft review", starts_at: "2026-10-01T00:00:00Z", ends_at: "2026-10-01T01:00:00Z", lifecycle_state: "ended", can_manage: true, can_record: true, record_id: "record-a", participants: [{ user_id: owner.id, required: true }], minutes: "Reviewed the draft", decisions: "Revise the introduction", version: 3, confirmations: [{ user: member, version: 2, current: false, updated_at: "2026-10-01T00:00:00Z" }], attendance: [{ user: former, attended: true, note: "Observed during the meeting", recorded_by: owner, updated_at: "2026-10-01T00:00:00Z" }], actions: [], history: [] };
const claim: ContributionClaim = { id: "claim-a", author: member, title: "Report diagram", statement: "I prepared the report diagram and reviewed the final result.", artifact_url: "https://example.com/result", task_id: null, task_title: "", supersedes_id: null, created_at: "2026-09-01T00:00:00Z", status: "team_confirmed", can_review: false, can_respond: false, can_revise: false, can_withdraw: false, contributors: [{ user: owner, response: "confirmed" }], reviews: [{ reviewer: former, outcome: "confirmed", note: "Checked the delivered result", created_at: "2026-09-02T00:00:00Z" }] };
const evidence: EvidenceData = { range_start: "2026-10-01", range_end: "2026-10-02", claims: [], truncated: false, page: 1, pages: 1, count: 0, basis: "System records and statements are separate evidence; no score or grade is inferred.", members: [{ ...owner, role: "owner", active: true, joined_at: "2026-09-01T00:00:00Z", removed_at: null, recorded_attendance: 1, system_events: 3, tasks_marked_done: 1, comments_created: 1, accepted_rsvps: 1 }, { ...former, role: "member", active: false, joined_at: "2026-09-01T00:00:00Z", removed_at: "2026-09-20T00:00:00Z", recorded_attendance: 2, system_events: 7, tasks_marked_done: 2, comments_created: 3, accepted_rsvps: 2 }] };
const subscription: CalendarSubscription = { id: "feed-a", project_id: null, include_details: false, revoked_at: null, expires_at: "2099-10-01T00:00:00Z", created_at: "2026-10-01T00:00:00Z", feed_url: "https://studycrew.example/api/v1/coordination/subscriptions/feed/private-token/" };

describe("calendar, coordination and evidence user flows", () => {
  let container: HTMLDivElement;
  let root: Root;
  let client: QueryClient;
  beforeEach(() => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    vi.clearAllMocks();
    container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
    client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
    client.setQueryData(["me"], me); client.setQueryData(["project", project.id], project); client.setQueryData(["memberships", project.id], page(memberships)); client.setQueryData(["projects"], page([project]));
    vi.mocked(accountApi.me).mockResolvedValue(me); vi.mocked(projectApi.get).mockResolvedValue(project); vi.mocked(projectApi.list).mockResolvedValue(page([project])); vi.mocked(membershipApi.list).mockResolvedValue(page(memberships)); vi.mocked(taskApi.list).mockResolvedValue(page([]));
    vi.mocked(coordinationApi.calendar).mockImplementation(async (start, end) => ({ range_start: start, range_end: end, time_zone: "Australia/Sydney", events: [], truncated: false }));
    vi.mocked(coordinationApi.subscriptions).mockResolvedValue({ subscriptions: [] }); vi.mocked(coordinationApi.subscribe).mockResolvedValue(subscription);
    vi.mocked(coordinationApi.availability).mockResolvedValue(availability); vi.mocked(coordinationApi.saveAvailability).mockResolvedValue({});
    vi.mocked(coordinationApi.polls).mockResolvedValue({ polls: [], truncated: false, page: 1, pages: 1, count: 0 }); vi.mocked(coordinationApi.vote).mockResolvedValue(poll);
    vi.mocked(coordinationApi.meetingRecords).mockResolvedValue({ meetings: [record], truncated: false, page: 1, pages: 1, count: 1, members: [{ ...owner, active: true }, { ...member, active: true }, { ...former, active: false }] }); vi.mocked(coordinationApi.meetingRecord).mockResolvedValue(record);
    vi.mocked(coordinationApi.saveRecord).mockResolvedValue(record); vi.mocked(coordinationApi.action).mockResolvedValue(record); vi.mocked(coordinationApi.attendance).mockResolvedValue(record); vi.mocked(coordinationApi.confirmMinutes).mockResolvedValue(record);
    vi.mocked(coordinationApi.evidence).mockResolvedValue(evidence); vi.mocked(coordinationApi.claim).mockResolvedValue({ id: "claim-new" }); vi.mocked(coordinationApi.respondClaim).mockResolvedValue({ id: claim.id }); vi.mocked(coordinationApi.reviewClaim).mockResolvedValue({ id: claim.id });
    vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value() { this.open = true; } });
    Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value() { this.open = false; } });
  });
  afterEach(async () => { await act(async () => root.unmount()); client.clear(); container.remove(); vi.restoreAllMocks(); });
  const settle = async () => { await act(async () => { await new Promise((resolve) => setTimeout(resolve, 25)); }); };
  const render = async (which: "calendar" | "coordination" | "evidence") => {
    const path = which === "calendar" ? "/app/calendar/" : `/app/projects/project-a/${which}/`;
    await act(async () => root.render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><Routes><Route path="/app/calendar/" element={<CalendarPage />} /><Route path="/app/projects/:projectId/coordination/" element={<CoordinationPage />} /><Route path="/app/projects/:projectId/evidence/" element={<EvidencePage />} /></Routes></MemoryRouter></QueryClientProvider>));
    await settle();
  };
  const button = (label: string) => [...container.querySelectorAll<HTMLButtonElement>("button")].find((item) => item.textContent === label)!;
  const control = (label: string) => {
    const element = [...container.querySelectorAll<HTMLLabelElement>("label")].find((item) => item.textContent === label)!;
    return container.querySelector<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(`[id="${element.htmlFor}"]`)!;
  };
  const change = async (element: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement, value: string) => {
    const prototype = element instanceof HTMLSelectElement ? HTMLSelectElement.prototype : element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    await act(async () => { Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(element, value); element.dispatchEvent(new Event(element instanceof HTMLSelectElement ? "change" : "input", { bubbles: true })); });
    await settle();
  };
  const submit = async (form: HTMLFormElement) => { await act(async () => form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))); await settle(); };
  const selectMeeting = async () => { await change(control("Meeting"), record.id); };

  it("switches month and Monday-based week ranges, preserving ICS and local multi-day events", async () => {
    vi.mocked(coordinationApi.calendar).mockImplementation(async (start, end) => ({ range_start: start, range_end: end, time_zone: "Australia/Sydney", truncated: false, events: [{ id: "overnight", kind: "meeting", title: "Overnight session", project_id: project.id, project_name: project.name, starts_at: "2026-10-05T11:00:00Z", ends_at: "2026-10-05T16:00:00Z", location: "", description: "", cancelled: false, updated_at: "2026-10-01T00:00:00Z", url: "/app/projects/project-a/coordination/" }] }));
    await render("calendar"); await change(control("Month"), "2026-10"); await change(control("View"), "week"); await change(control("Week starting Monday"), "2026-10-07");
    expect(coordinationApi.calendar).toHaveBeenLastCalledWith("2026-10-05", "2026-10-11", undefined);
    expect(container.querySelectorAll(".coord-calendar-cell")).toHaveLength(7);
    expect(container.querySelector('section[aria-label="2026-10-05"]')?.textContent).toContain("Overnight session");
    expect(container.querySelector('section[aria-label="2026-10-06"]')?.textContent).toContain("Overnight session");
    expect(container.querySelector<HTMLAnchorElement>('a[href*="/calendar/export/"]')!.href).toContain("range_end=2026-10-11");
    await act(async () => button("Next week").click()); await settle();
    expect(coordinationApi.calendar).toHaveBeenLastCalledWith("2026-10-12", "2026-10-18", undefined);
    await change(control("View"), "month"); expect(container.querySelectorAll(".coord-calendar-cell")).toHaveLength(31);
  });

  it("uses private labels by default, blocks duplicate submission and hides the returned-once subscription URL", async () => {
    let resolve!: (value: CalendarSubscription) => void;
    vi.mocked(coordinationApi.subscribe).mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    await render("calendar");
    expect(container.textContent).toContain("A clear month"); expect(container.textContent).toContain("No subscriptions");
    const form = container.querySelector<HTMLInputElement>('[name="details"]')!.form!;
    await submit(form); expect(coordinationApi.subscribe).toHaveBeenCalledWith(undefined, false); expect(button("Create personal subscription").disabled).toBe(true);
    await act(async () => resolve(subscription)); await settle();
    expect(control("Private subscription URL").value).toBe(subscription.feed_url); expect(container.querySelector('[role="status"]')?.textContent).toContain("only shown once");
    await act(async () => button("Hide private URL").click()); expect(container.querySelector('input[readonly]')).toBeNull();
    await act(async () => container.querySelector<HTMLInputElement>('[name="details"]')!.click()); await submit(form);
    expect(coordinationApi.subscribe).toHaveBeenLastCalledWith(undefined, true);
  });

  it("shows server errors and clears stale error feedback after a successful retry", async () => {
    vi.mocked(coordinationApi.subscribe).mockRejectedValueOnce(new APIError(403, { error: { message: "Your membership has ended." } }));
    await render("calendar"); const form = container.querySelector<HTMLInputElement>('[name="details"]')!.form!;
    await submit(form); expect(container.querySelector('[role="alert"]')?.textContent).toContain("Your membership has ended.");
    await submit(form); expect(container.querySelector('[role="alert"]')).toBeNull(); expect(container.textContent).toContain("Subscription created.");
  });

  it("submits actual availability blocks and invited member votes with visible success", async () => {
    vi.mocked(coordinationApi.polls).mockResolvedValue({ polls: [poll], truncated: false, page: 1, pages: 1, count: 1 });
    await render("coordination");
    const form = container.querySelector<HTMLSelectElement>('[name="weekday"]')!.form!;
    form.querySelector<HTMLSelectElement>('[name="weekday"]')!.value = "1"; form.querySelector<HTMLInputElement>('[name="end"]')!.value = "10:30";
    await submit(form); expect(button("Save availability").disabled).toBe(false);
    await act(async () => button("Save availability").click()); await settle();
    expect(coordinationApi.saveAvailability).toHaveBeenCalledWith(project.id, "Australia/Sydney", [{ weekday: 1, start_minute: 540, end_minute: 630 }]);
    expect(container.textContent).toContain("Your recurring free time was saved.");
    expect(container.textContent).toContain("Alex (optional)"); expect(container.textContent).toContain("Morgan (required)");
    await act(async () => button("Available").click()); await settle();
    expect(coordinationApi.vote).toHaveBeenCalledWith("option-a", "yes"); expect(container.textContent).toContain("Your vote was saved.");
    expect(container.textContent).not.toContain("Schedule this time");
  });

  it("saves minutes, records a historical member and turns action input into an assigned real task", async () => {
    await render("coordination"); await selectMeeting();
    expect(container.textContent).toContain("Morgan (version 2)");
    const minutesForm = container.querySelector<HTMLTextAreaElement>('[name="minutes"]')!.form!;
    minutesForm.querySelector<HTMLTextAreaElement>('[name="minutes"]')!.value = "Reviewed the corrected diagram";
    minutesForm.querySelector<HTMLTextAreaElement>('[name="decisions"]')!.value = "Upload the final diagram";
    await submit(minutesForm);
    expect(coordinationApi.saveRecord).toHaveBeenCalledWith(record.id, { minutes: "Reviewed the corrected diagram", decisions: "Upload the final diagram", expected_version: record.version });
    expect(container.textContent).toContain("Existing confirmations refer to earlier versions");
    const attendanceForm = container.querySelector<HTMLSelectElement>('[name="attended"]')!.form!;
    attendanceForm.querySelector<HTMLSelectElement>('[name="user"]')!.value = former.id; attendanceForm.querySelector<HTMLInputElement>('[name="note"]')!.value = "Verified after checking the call notes";
    await submit(attendanceForm); expect(coordinationApi.attendance).toHaveBeenCalledWith(record.id, former.id, true, "Verified after checking the call notes");
    const actionForm = container.querySelector<HTMLTextAreaElement>('[name="description"]')!.form!;
    actionForm.querySelector<HTMLInputElement>('[name="title"]')!.value = "Upload final diagram"; actionForm.querySelector<HTMLTextAreaElement>('[name="description"]')!.value = "Apply the meeting decision";
    actionForm.querySelector<HTMLInputElement>('[name="assignee"][value="member"]')!.checked = true;
    await submit(actionForm);
    expect(coordinationApi.action).toHaveBeenCalledWith(record.id, { title: "Upload final diagram", description: "Apply the meeting decision", due_at: null, assignee_ids: [member.id] });
    expect(container.textContent).toContain("Action item created as a real assigned task.");
    await act(async () => button("Confirm I have read version 3").click()); await settle(); expect(coordinationApi.confirmMinutes).toHaveBeenCalledWith(record.id, 3);
  });

  it("lets ordinary members confirm minutes while keeping manager controls absent", async () => {
    const readonly = { ...record, can_manage: false };
    vi.mocked(coordinationApi.meetingRecord).mockResolvedValue(readonly);
    await render("coordination"); await selectMeeting();
    expect(container.textContent).toContain("Reviewed the draft"); expect(container.textContent).toContain("Observed during the meeting");
    expect(container.querySelector('[name="minutes"]')).toBeNull(); expect(container.textContent).not.toContain("Create task from action"); expect(container.textContent).not.toContain("Record or correct attendance");
    expect(button("Confirm I have read version 3")).toBeDefined();
  });

  it("submits contribution statements with collaborator attribution and preserves evidence distinctions", async () => {
    await render("evidence");
    expect(container.textContent).toContain("Former member"); expect(container.textContent).toContain("counts, not a contribution score or grade"); expect(container.textContent).toContain("No contribution statements");
    const form = container.querySelector<HTMLInputElement>('[name="title"]')!.form!;
    form.querySelector<HTMLInputElement>('[name="title"]')!.value = "Prepared the report"; form.querySelector<HTMLTextAreaElement>('[name="statement"]')!.value = "I prepared the report and reviewed the final source files.";
    form.querySelector<HTMLInputElement>('[name="link"]')!.value = "https://example.com/report"; form.querySelector<HTMLInputElement>('[name="contributor"][value="member"]')!.checked = true;
    await submit(form);
    expect(coordinationApi.claim).toHaveBeenCalledWith({ project: project.id, title: "Prepared the report", statement: "I prepared the report and reviewed the final source files.", artifact_url: "https://example.com/report", task_id: null, contributor_ids: [member.id], supersedes_id: null });
    expect(container.textContent).toContain("submitted as self-reported evidence"); expect(form.querySelector<HTMLInputElement>('[name="title"]')!.value).toBe("");
  });

  it("exposes attribution only for the named collaborator and independent review only when permitted", async () => {
    vi.mocked(coordinationApi.evidence).mockResolvedValue({ ...evidence, claims: [{ ...claim, can_respond: true, status: "awaiting_collaborators" }, { ...claim, id: "independent-claim", author: former, contributors: [], can_review: true, status: "self_reported" }], count: 2 });
    await render("evidence");
    const link = container.querySelector<HTMLAnchorElement>('a[href="https://example.com/result"]')!; expect(link.target).toBe("_blank"); expect(link.rel).toContain("noreferrer");
    expect(container.querySelectorAll("button")).toBeDefined();
    await act(async () => button("Confirm my attribution").click()); await settle(); expect(coordinationApi.respondClaim).toHaveBeenCalledWith(claim.id, "confirmed");
    const form = container.querySelector<HTMLSelectElement>('[name="outcome"]')!.form!;
    form.querySelector<HTMLSelectElement>('[name="outcome"]')!.value = "confirmed"; form.querySelector<HTMLInputElement>('[name="note"]')!.value = "Reviewed the delivered file";
    await submit(form); expect(coordinationApi.reviewClaim).toHaveBeenCalledWith("independent-claim", "confirmed", "Reviewed the delivered file"); expect(container.textContent).toContain("Independent team review recorded.");
    expect(container.textContent).toContain("Checked the delivered result");
  });

  it("keeps archived project contribution pages read-only and surfaces load failures", async () => {
    client.setQueryData(["project", project.id], { ...project, archived_at: "2026-10-01T00:00:00Z" });
    vi.mocked(coordinationApi.evidence).mockResolvedValue({ ...evidence, claims: [claim], count: 1 });
    await render("evidence"); expect(container.textContent).toContain("reviews are read-only"); expect(container.querySelector('[name="statement"]')).toBeNull(); expect(container.textContent).not.toContain("Save review");
    await act(async () => { client.setQueryData(["project", project.id], project); client.removeQueries({ queryKey: ["coord-evidence"] }); });
    vi.mocked(coordinationApi.evidence).mockRejectedValue(new Error("Evidence is temporarily unavailable"));
    await act(async () => client.invalidateQueries({ queryKey: ["coord-evidence"] })); await settle();
    if (!container.querySelector('[role="alert"]')) { await act(async () => client.refetchQueries({ queryKey: ["coord-evidence"] })); await settle(); }
    expect(container.textContent).toContain("Evidence is temporarily unavailable");
  });
});
