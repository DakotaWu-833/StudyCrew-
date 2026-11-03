import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Layout from "./Layout";

vi.mock("./BrowserReadiness", () => ({ default: () => null }));

describe("workspace sidebar navigation", () => {
  let container: HTMLDivElement;
  let root: Root;
  let client: QueryClient;

  beforeEach(() => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    localStorage.clear();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    for (const key of [["notifications", "unread"], ["scheduled-alerts"], ["service-notices"]]) {
      client.setQueryData(key, { count: 1, results: [] });
    }
    client.setQueryData(["projects", "all"], { results: [
      { id: "project", name: "Study group", archived_at: null },
    ] });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    client.clear();
    container.remove();
    vi.restoreAllMocks();
  });

  async function render(path = "/app/", moderator = true) {
    client.setQueryData(["me"], { user: { id: "user", display_name: "Alex" },
      email: "alex@example.com", profile: {}, permissions: { site_moderator: moderator } });
    await act(async () => root.render(<QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}><Routes>
        <Route path="/app/*" element={<Layout />}><Route path="*" element={<p>Current page</p>} /></Route>
      </Routes></MemoryRouter>
    </QueryClientProvider>));
  }

  async function click(element: Element) {
    await act(async () => element.dispatchEvent(new MouseEvent("click", { bubbles: true })));
  }
  const button = (name: string) => container.querySelector<HTMLButtonElement>(`button[aria-label="${name}"]`)!;
  const settingsButton = () => container.querySelector<HTMLButtonElement>(".sidebar__settings-toggle")!;
  const settings = () => container.querySelector<HTMLElement>('nav[aria-label="Settings"]')!;

  it("keeps functional links and projects above a separate settings disclosure", async () => {
    await render();
    const main = container.querySelector('nav[aria-label="Main"]')!;
    expect([...main.querySelectorAll("a")].map(link => link.getAttribute("aria-label"))).toEqual([
      "Overview", "My studies", "Find a team", "Calendar", "Invitations", "Notifications", "Offline tasks",
    ]);
    expect(main.querySelector(".nav-count")?.textContent).toBe("2");
    expect(container.querySelector(".project-link")?.textContent).toBe("Study group");
    expect(settings().hidden).toBe(true);
    await click(settingsButton());
    expect(settingsButton().getAttribute("aria-expanded")).toBe("true");
    expect(settings().hidden).toBe(false);
    expect([...settings().querySelectorAll("a")].map(link => link.getAttribute("aria-label"))).toEqual([
      "Profile", "Notification settings", "Security & privacy", "Help & feedback", "Service operations",
    ]);
    await click(settingsButton());
    expect(settings().hidden).toBe(true);
  });

  it("opens settings on a direct settings route and keeps its active link", async () => {
    await render("/app/security/");
    expect(settings().hidden).toBe(false);
    expect(settings().querySelector('a[aria-current="page"]')?.textContent).toContain("Security & privacy");
  });

  it("keeps moderator-only operations out of ordinary users' settings", async () => {
    await render("/app/profile/", false);
    expect(settings().hidden).toBe(false);
    expect(settings().querySelector('a[href="/app/operations/"]')).toBeNull();
  });

  it("hides the full navigation while collapsed, preserves the page and restores the saved choice", async () => {
    await render();
    await click(button("Collapse sidebar"));
    expect(container.querySelector<HTMLElement>("#workspace-sidebar-content")?.hidden).toBe(true);
    expect(container.querySelector("main")?.textContent).toContain("Current page");
    expect(localStorage.getItem("studycrew.sidebar.collapsed")).toBe("true");
    await act(async () => root.unmount());
    root = createRoot(container);
    await render();
    expect(button("Expand sidebar").getAttribute("aria-expanded")).toBe("false");
    await click(button("Expand sidebar"));
    expect(container.querySelector<HTMLElement>("#workspace-sidebar-content")?.hidden).toBe(false);
    expect(localStorage.getItem("studycrew.sidebar.collapsed")).toBe("false");
  });

  it("still expands and collapses when browser storage is blocked", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("Blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("Blocked"); });
    await render();
    await click(button("Collapse sidebar"));
    await click(button("Expand sidebar"));
    expect(container.querySelector<HTMLElement>("#workspace-sidebar-content")?.hidden).toBe(false);
  });
});
