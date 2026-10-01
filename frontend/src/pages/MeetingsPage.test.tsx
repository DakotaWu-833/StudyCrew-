import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { APIError } from "../api/client";
import { accountApi, meetingApi, projectApi } from "../api/resources";
import type { Me, Meeting, Page, Project } from "../api/types";
import MeetingsPage from "./MeetingsPage";

let projectId = "project-one";
vi.mock("react-router-dom", () => ({ useParams: () => ({ projectId }) }));
vi.mock("../api/resources", () => ({
  accountApi: { me: vi.fn() }, projectApi: { get: vi.fn() },
  meetingApi: { list: vi.fn(), listPage: vi.fn(), create: vi.fn(), update: vi.fn(), rsvp: vi.fn(),
    cancel: vi.fn(), archive: vi.fn(), restore: vi.fn(), sendReminder: vi.fn(), holiday: vi.fn() },
}));

const user = { id: "member", display_name: "Alex Morgan" };
const me: Me = { user, email: "alex@example.com", profile: {
  email: "alex@example.com", display_name: user.display_name, course_code: "", time_zone: "Australia/Sydney",
  biography: "", avatar_url: "", avatar_image_url: "", updated_at: "2026-10-01T00:00:00Z",
}, permissions: { site_moderator: false } };
const project: Project = { id: projectId, name: "Team project", description: "", due_at: null, created_by: user,
  created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z", archived_at: null, current_user_role: "member", member_count: 2 };
const meeting = (number: number): Meeting => ({ id: `meeting-${number}`, project: projectId, organiser: user,
  title: `Session ${number}`, starts_at: "2030-10-02T00:00:00Z", ends_at: "2030-10-02T01:00:00Z",
  location: "Library", agenda: "Review the project", cancelled_at: null, archived_at: null, lifecycle_state: "scheduled",
  created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
  attendance_counts: { accepted: 1, pending: 0, declined: 0 }, my_response: "accepted", my_availability_note: "",
});
const resultPage = (page = 1, count = 12): Page<Meeting> => ({ count,
  next: page * 5 < count ? "/next" : null, previous: page > 1 ? "/previous" : null,
  results: Array.from({ length: Math.min(5, Math.max(0, count - (page - 1) * 5)) }, (_, index) => meeting((page - 1) * 5 + index + 1)),
});
const originalDialogMethods = {
  showModal: Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "showModal"),
  close: Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "close"),
};
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe("MeetingsPage server collections", () => {
  let container: HTMLDivElement;
  let root: Root;
  let client: QueryClient;

  beforeEach(() => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    vi.useFakeTimers(); vi.clearAllMocks(); projectId = "project-one";
    Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function (this: HTMLDialogElement) { this.setAttribute("open", ""); } });
    Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function (this: HTMLDialogElement) { this.removeAttribute("open"); } });
    container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
    client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
    client.setQueryData(["me"], me); client.setQueryData(["project", projectId], project);
    vi.mocked(meetingApi.listPage).mockImplementation(async (_, filters) => resultPage(filters?.page));
  });

  afterEach(async () => {
    await act(async () => root.unmount()); client.clear(); container.remove(); vi.useRealTimers(); vi.restoreAllMocks();
    for (const method of ["showModal", "close"] as const) {
      const descriptor = originalDialogMethods[method];
      if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, method, descriptor);
      else Reflect.deleteProperty(HTMLDialogElement.prototype, method);
    }
  });
  async function flush(milliseconds = 1) {
    await act(async () => { await vi.advanceTimersByTimeAsync(milliseconds); });
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  }
  async function render() {
    await act(async () => root.render(<QueryClientProvider client={client}><MeetingsPage /></QueryClientProvider>));
    await flush();
  }
  function button(text: string) { return Array.from(container.querySelectorAll<HTMLButtonElement>("button")).find((item) => item.textContent === text)!; }
  async function click(text: string) { await act(async () => button(text).click()); await flush(); }
  async function setSearch(value: string) {
    const input = container.querySelector<HTMLInputElement>('input[type="search"]')!;
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
  }
  async function changeTitle(value: string) {
    const input = container.querySelector<HTMLInputElement>('dialog input[name="title"]')!;
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
  }
  async function setStatus(value: string) {
    const select = container.querySelector<HTMLSelectElement>(".meeting-filters select")!;
    await act(async () => { select.value = value; select.dispatchEvent(new Event("change", { bubbles: true })); }); await flush();
  }

  it("fetches one server page and navigation requests the next five records", async () => {
    await render();
    expect(meetingApi.list).not.toHaveBeenCalled();
    expect(container.querySelectorAll(".meeting-list > .panel")).toHaveLength(5);
    expect(container.textContent).toContain("Showing 1–5 of 12");
    await click("Next");
    expect(meetingApi.listPage).toHaveBeenLastCalledWith(projectId, { scope: "active", state: "all", search: "", page: 2 });
    expect(Array.from(container.querySelectorAll(".meeting h3")).map((heading) => heading.textContent)).toEqual(["Session 6", "Session 7", "Session 8", "Session 9", "Session 10"]);
  });

  it("debounces encoded search input and resets status/search/scope navigation to page one", async () => {
    await render(); await click("Next"); await setSearch("launch & review"); await flush(301);
    expect(meetingApi.listPage).toHaveBeenLastCalledWith(projectId, { scope: "active", state: "all", search: "launch & review", page: 1 });
    await setStatus("ended");
    expect(meetingApi.listPage).toHaveBeenLastCalledWith(projectId, { scope: "active", state: "ended", search: "launch & review", page: 1 });
    await click("Archived");
    expect(meetingApi.listPage).toHaveBeenLastCalledWith(projectId, { scope: "archived", state: "ended", search: "launch & review", page: 1 });
    await click("Clear filters");
    expect(meetingApi.listPage).toHaveBeenLastCalledWith(projectId, { scope: "archived", state: "all", search: "", page: 1 });
  });

  it("retains input focus and previous same-project content while filtering updates", async () => {
    await render(); const pending = deferred<Page<Meeting>>();
    vi.mocked(meetingApi.listPage).mockReturnValue(pending.promise);
    const input = container.querySelector<HTMLInputElement>('input[type="search"]')!; input.focus();
    await setSearch("pending"); await flush(301);
    expect(document.activeElement).toBe(input); expect(container.textContent).toContain("Session 1");
    expect(container.textContent).toContain("Updating meetings…"); expect(button("Next").disabled).toBe(true);
    await act(async () => pending.resolve(resultPage(1, 1))); await flush();
    expect(document.activeElement).toBe(input); expect(container.textContent).toContain("1 matching meeting");
  });

  it("never displays the previous project collection while another project loads", async () => {
    await render(); const pending = deferred<Page<Meeting>>();
    vi.mocked(meetingApi.listPage).mockReturnValue(pending.promise); projectId = "project-two";
    client.setQueryData(["project", projectId], { ...project, id: projectId }); await render();
    expect(container.textContent).not.toContain("Session 1"); expect(container.textContent).toContain("Loading meeting records…");
    await act(async () => pending.resolve(resultPage(1, 0))); await flush(); expect(container.textContent).toContain("No current meetings");
  });

  it("keeps search controls usable on failure and retries the failed query", async () => {
    vi.mocked(meetingApi.listPage).mockRejectedValueOnce(new Error("Connection unavailable"));
    await render(); expect(container.textContent).toContain("Connection unavailable");
    expect(container.querySelector('input[type="search"]')).not.toBeNull();
    await click("Try again"); expect(container.textContent).toContain("Session 1");
  });

  it("shows matching empty-state copy and clear filters restores current records", async () => {
    await render(); vi.mocked(meetingApi.listPage).mockResolvedValueOnce(resultPage(1, 0));
    await setSearch("unknown"); await flush(301); expect(container.textContent).toContain("No matching meetings");
    await click("Clear filters"); expect(container.textContent).toContain("Session 1");
  });

  it("recovers page one when a removed last record invalidates the requested page", async () => {
    await render(); vi.mocked(meetingApi.listPage).mockRejectedValueOnce(new APIError(404, { error: { code: "not_found", message: "Invalid page." } }));
    await click("Next"); await flush();
    expect(container.textContent).toContain("Session 1");
    expect(meetingApi.listPage).toHaveBeenCalledWith(projectId, { scope: "active", state: "all", search: "", page: 2 });
    expect(button("Previous").disabled).toBe(true);
  });

  it("protects changed meeting details and does not warn after values are restored", async () => {
    await render(); await click("Edit meeting"); await changeTitle("Unsaved planning details");
    await act(async () => container.querySelector<HTMLButtonElement>('[aria-label="Close Edit meeting"]')!.click());
    expect(container.textContent).toContain("Discard unsaved changes?"); await click("Keep editing");
    await changeTitle("Session 1");
    await act(async () => container.querySelector<HTMLButtonElement>('[aria-label="Close Edit meeting"]')!.click());
    await flush(181); expect(container.querySelector("dialog")).toBeNull(); expect(meetingApi.update).not.toHaveBeenCalled();
  });

  it("blocks editor dismissal while saving and associates server errors with the field", async () => {
    await render(); await click("Edit meeting"); await changeTitle("Updated planning details");
    const pending = deferred<Meeting>(); vi.mocked(meetingApi.update).mockReturnValue(pending.promise);
    await act(async () => container.querySelector<HTMLFormElement>("dialog form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(container.querySelector<HTMLButtonElement>('[aria-label="Close Edit meeting"]')!.disabled).toBe(true);
    expect(container.querySelector("dialog")?.getAttribute("aria-busy")).toBe("true");
    await act(async () => pending.resolve(meeting(1))); await flush(); expect(container.querySelector("dialog")).toBeNull();

    await click("Edit meeting"); vi.mocked(meetingApi.update).mockRejectedValueOnce(new APIError(400, { error: { fields: { starts_at: ["Choose a future date."] } } }));
    await act(async () => container.querySelector<HTMLFormElement>("dialog form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    await flush(); const start = container.querySelector<HTMLInputElement>('dialog input[name="starts_at"]')!;
    expect(start.getAttribute("aria-invalid")).toBe("true");
    const descriptions = start.getAttribute("aria-describedby")!.split(" ").map((id) => document.getElementById(id)?.textContent);
    expect(descriptions).toContain("Choose a future date.");
  });

  it("retains read-only archived evidence and keeps reminder sending manager-only", async () => {
    await render(); expect(button("Email reminder")).toBeUndefined();
    client.setQueryData(["project", projectId], { ...project, current_user_role: "owner" }); await flush();
    expect(button("Email reminder")).not.toBeUndefined();
    vi.mocked(meetingApi.listPage).mockResolvedValueOnce({ count: 1, next: null, previous: null, results: [{ ...meeting(1), lifecycle_state: "archived", cancelled_at: "2026-10-01T00:00:00Z", archived_at: "2026-10-01T01:00:00Z" }] });
    await click("Archived"); expect(container.textContent).toContain("retained as read-only");
    expect(container.querySelector(".rsvp-form")).toBeNull(); expect(button("Edit meeting")).toBeUndefined();
    expect(button("Restore to current")).not.toBeUndefined(); expect(button("Email reminder")).toBeUndefined();
  });
});
