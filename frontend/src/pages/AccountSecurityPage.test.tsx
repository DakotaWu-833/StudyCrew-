import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { accountReadinessApi, type AccountSecuritySummary } from "../api/accountReadiness";
import { APIError } from "../api/client";
import AccountSecurityPage from "./AccountSecurityPage";

vi.mock("../api/accountReadiness", () => ({ accountReadinessApi: {
  summary: vi.fn(), reauthenticate: vi.fn(), requestRecoveryEmail: vi.fn(), removeRecoveryEmail: vi.fn(),
  revokeDevice: vi.fn(), revokeOthers: vi.fn(), download: vi.fn(), close: vi.fn(),
} }));

const summary: AccountSecuritySummary = {
  recovery_email: null,
  devices: [{ id: "mine", browser: "My browser", current: true, first_seen_at: "2026-10-01T00:00:00Z", last_seen_at: "2026-10-01T00:00:00Z", expires_at: "2026-10-01T01:00:00Z" }],
  owned_projects: [],
  privacy: { version: "2026-10-01", visibility: ["Shared project profile"], retention: ["Immutable evidence remains"], download: "Your records without security secrets" },
  verification_minutes: 5,
};

describe("AccountSecurityPage", () => {
  let container: HTMLDivElement;
  let root: Root;
  let client: QueryClient;

  beforeEach(() => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    vi.clearAllMocks();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
    vi.mocked(accountReadinessApi.summary).mockResolvedValue(summary);
    vi.mocked(accountReadinessApi.reauthenticate).mockResolvedValue({ message: "Password confirmed.", valid_for_seconds: 300 });
    vi.mocked(accountReadinessApi.requestRecoveryEmail).mockResolvedValue({ message: "Verification link sent." });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    client.clear();
    container.remove();
    vi.restoreAllMocks();
  });

  async function render(data = summary) {
    client.setQueryData(["account-security"], data);
    await act(async () => root.render(<MemoryRouter><QueryClientProvider client={client}><AccountSecurityPage /></QueryClientProvider></MemoryRouter>));
  }

  async function settle() { await act(async () => { await new Promise((resolve) => setTimeout(resolve, 25)); }); }

  async function unlock() {
    const input = container.querySelector<HTMLInputElement>('[name="current_password"]')!;
    input.value = "ValidPass!234";
    await act(async () => input.closest("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    await settle();
  }

  function button(label: string) { return [...container.querySelectorAll<HTMLButtonElement>("button")].find((item) => item.textContent === label)!; }

  it("locks sensitive actions and shows honest evidence retention and recovery requirements", async () => {
    await render();
    expect(button("Send verification link").disabled).toBe(true);
    expect(button("Download my data").disabled).toBe(true);
    expect(button("Sign out all other devices").disabled).toBe(true);
    expect(container.textContent).toContain("existing password");
    expect(container.textContent).toContain("immutable audit evidence remain");
    expect(container.querySelector('a[href="/account/password/reset/"]')).not.toBeNull();
  });

  it("clears the password field and unlocks recovery only after successful reauthentication", async () => {
    await render();
    await unlock();
    expect(vi.mocked(accountReadinessApi.reauthenticate).mock.calls[0]?.[0]).toBe("ValidPass!234");
    expect(container.querySelector<HTMLInputElement>('[name="current_password"]')!.value).toBe("");
    expect(button("Send verification link").disabled).toBe(false);
    const input = container.querySelector<HTMLInputElement>('[name="email"]')!;
    input.value = "personal@example.com";
    await act(async () => input.closest("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    await settle();
    expect(accountReadinessApi.requestRecoveryEmail).toHaveBeenCalledWith("personal@example.com");
    expect(container.textContent).toContain("Verification link sent.");
  });

  it("keeps closure disabled while the user owns a project even after reauthentication", async () => {
    await render({ ...summary, owned_projects: [{ project_id: "team", project__name: "My team" }] });
    await unlock();
    expect(container.textContent).toContain("Transfer ownership");
    expect(container.textContent).toContain("My team");
    expect(button("Close my account").disabled).toBe(true);
  });

  it("locks sensitive actions again when the server says reauthentication expired", async () => {
    vi.mocked(accountReadinessApi.revokeOthers).mockRejectedValue(new APIError(403, { error: { message: "Confirm your password again." } }));
    await render();
    await unlock();
    await act(async () => button("Sign out all other devices").click());
    await settle();
    expect(container.textContent).toContain("Confirm your password again.");
    expect(button("Download my data").disabled).toBe(true);
  });
});
