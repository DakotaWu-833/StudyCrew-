import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { operationsApi, type NotificationPreferences } from "../api/operations";
import { accountApi, notificationApi, projectApi } from "../api/resources";
import NotificationSettingsPage from "./NotificationSettingsPage";
import NotificationsPage from "./NotificationsPage";
import SupportPage from "./SupportPage";
import OperationsPage from "./OperationsPage";

vi.mock("../api/operations", () => ({ operationsApi: {
  preferences: vi.fn(), updatePreferences: vi.fn(), mutes: vi.fn(), mute: vi.fn(),
  deliveries: vi.fn(), blocks: vi.fn(), block: vi.fn(), tickets: vi.fn(), createTicket: vi.fn(), reply: vi.fn(),
  alerts: vi.fn(), readAlert: vi.fn(), readAll: vi.fn(), summary: vi.fn(), adminTickets: vi.fn(), adminContacts: vi.fn(),
  adminDeliveries: vi.fn(), notices: vi.fn(), respondContact: vi.fn(), createNotice: vi.fn(), endNotice: vi.fn(), retryDelivery: vi.fn(),
} }));
vi.mock("../api/resources", () => ({ accountApi: { me: vi.fn() }, projectApi: { listAll: vi.fn() }, notificationApi: { list: vi.fn(), markRead: vi.fn() } }));

const preference: NotificationPreferences = { in_app: true, email: true, task_reminders: true, meeting_reminders: true,
  assignments: true, mentions: true, invitations: true, meeting_changes: true, digest: "off", quiet_start: null, quiet_end: null };

describe("notification and support workflows", () => {
  let container: HTMLDivElement, root: Root, cache: QueryClient;
  beforeEach(() => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); vi.clearAllMocks();
    container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
    cache = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
    cache.setQueryData(["notification-preferences"], preference); cache.setQueryData(["projects", "all"], { results: [] });
    cache.setQueryData(["project-mutes"], { results: [] }); cache.setQueryData(["deliveries"], { results: [] }); cache.setQueryData(["blocks"], { results: [] });
    vi.mocked(operationsApi.preferences).mockResolvedValue(preference); vi.mocked(operationsApi.updatePreferences).mockResolvedValue(preference);
    vi.mocked(operationsApi.mutes).mockResolvedValue({ results: [] }); vi.mocked(operationsApi.blocks).mockResolvedValue({ results: [] });
    vi.mocked(operationsApi.deliveries).mockResolvedValue({ results: [] }); vi.mocked(operationsApi.tickets).mockResolvedValue({ results: [] });
    vi.mocked(operationsApi.readAll).mockResolvedValue({});
  });
  afterEach(async () => { await act(async () => root.unmount()); cache.clear(); container.remove(); });
  async function render(node: ReactNode) { await act(async () => root.render(<QueryClientProvider client={cache}><MemoryRouter>{node}</MemoryRouter></QueryClientProvider>)); }
  async function settle() { await act(async () => { await new Promise(resolve => setTimeout(resolve, 25)); }); }
  async function submit(form: HTMLFormElement) { await act(async () => form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))); await settle(); }

  it("saves independent channels, quiet hours and digest using actual form values", async () => {
    await render(<NotificationSettingsPage />);
    const form = container.querySelector<HTMLFormElement>("form")!;
    form.querySelector<HTMLInputElement>('[name="in_app"]')!.checked = false;
    form.querySelector<HTMLSelectElement>('[name="digest"]')!.value = "weekly";
    form.querySelector<HTMLInputElement>('[name="quiet_start"]')!.value = "22:00";
    form.querySelector<HTMLInputElement>('[name="quiet_end"]')!.value = "08:00";
    await submit(form);
    expect(operationsApi.updatePreferences).toHaveBeenCalledWith(expect.objectContaining({ in_app: false, email: true, digest: "weekly", quiet_start: "22:00", quiet_end: "08:00" }), expect.anything());
    expect(container.textContent).toContain("preferences are saved");
    expect(container.textContent).toContain("Accepted means the mail server accepted");
  });

  it("keeps pending notification lists distinct from confirmed empty results", async () => {
    cache.removeQueries({ queryKey: ["blocks"] });
    cache.removeQueries({ queryKey: ["deliveries"] });
    vi.mocked(operationsApi.blocks).mockImplementation(() => new Promise(() => undefined));
    vi.mocked(operationsApi.deliveries).mockImplementation(() => new Promise(() => undefined));
    await render(<NotificationSettingsPage />);
    expect(container.textContent).toContain("Loading blocked people");
    expect(container.textContent).toContain("Loading email status");
    expect(container.textContent).not.toContain("No blocked people");
    expect(container.textContent).not.toContain("No email records");
  });

  it("shows notification-list failures without claiming the lists are empty", async () => {
    cache.removeQueries({ queryKey: ["blocks"] });
    cache.removeQueries({ queryKey: ["deliveries"] });
    vi.mocked(operationsApi.blocks).mockRejectedValue(new Error("Blocked people unavailable"));
    vi.mocked(operationsApi.deliveries).mockRejectedValue(new Error("Email status unavailable"));
    await render(<NotificationSettingsPage />); await settle();
    expect(container.textContent).toContain("Blocked people unavailable");
    expect(container.textContent).toContain("Email status unavailable");
    expect(container.textContent).not.toContain("No blocked people");
    expect(container.textContent).not.toContain("No email records");
  });

  it("shows reminder content separately from activity and supports marking both read", async () => {
    const alerts = { count: 1, results: [{ id: "reminder", project: "team", project_name: "Private team", category: "task_due", title: "Due soon: Research", body: "Check your research task.", target_url: "/app/projects/team/tasks/task/", created_at: "2026-10-01T00:00:00Z", read_at: null }] };
    cache.setQueryData(["scheduled-alerts"], alerts); cache.setQueryData(["notifications", "all"], { count: 0, results: [] });
    vi.mocked(operationsApi.alerts).mockResolvedValue(alerts); vi.mocked(notificationApi.list).mockResolvedValue({ count: 0, results: [] } as never);
    await render(<NotificationsPage />);
    expect(container.textContent).toContain("Due soon: Research"); expect(container.textContent).not.toContain("You are up to date");
    const button = [...container.querySelectorAll<HTMLButtonElement>("button")].find(row => row.textContent === "Mark all read")!;
    await act(async () => button.click()); await settle();
    expect(operationsApi.readAll).toHaveBeenCalledOnce();
  });

  it("submits a privacy support case with the user's entered description", async () => {
    cache.setQueryData(["support"], { results: [] });
    vi.mocked(operationsApi.createTicket).mockResolvedValue({ id: "case", category: "privacy", subject: "Data export", description: "I need help downloading my data.", status: "open", resolution: "", created_at: "2026-10-01", updated_at: "2026-10-01", replies: [] });
    await render(<SupportPage />);
    const form = container.querySelector<HTMLFormElement>("form")!;
    form.querySelector<HTMLSelectElement>('[name="category"]')!.value = "privacy";
    form.querySelector<HTMLInputElement>('[name="subject"]')!.value = "Data export";
    form.querySelector<HTMLTextAreaElement>('[name="description"]')!.value = "I need help downloading my data.";
    await submit(form);
    expect(operationsApi.createTicket).toHaveBeenCalledWith({ category: "privacy", subject: "Data export", description: "I need help downloading my data." }, expect.anything());
    expect(container.textContent).toContain("Your request has been saved");
    expect(form.querySelector<HTMLInputElement>('[name="subject"]')!.value).toBe("");
  });

  it("does not load the moderator inbox for a student", async () => {
    cache.setQueryData(["me"], { permissions: { site_moderator: false } });
    await render(<OperationsPage />);
    expect(container.textContent).toContain("Site moderator permission is required");
    expect(operationsApi.adminTickets).not.toHaveBeenCalled(); expect(operationsApi.adminContacts).not.toHaveBeenCalled();
    expect(operationsApi.summary).not.toHaveBeenCalled();
  });

  it("shows an account lookup error instead of a moderator permission denial", async () => {
    vi.mocked(accountApi.me).mockRejectedValue(new Error("Account details unavailable"));
    await render(<OperationsPage />); await settle();
    expect(container.textContent).toContain("Account details unavailable");
    expect(container.textContent).not.toContain("Site moderator permission is required");
    expect(operationsApi.adminTickets).not.toHaveBeenCalled();
  });
});
