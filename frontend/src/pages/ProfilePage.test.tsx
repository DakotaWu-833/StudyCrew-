import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { accountApi } from "../api/resources";
import { APIError } from "../api/client";
import type { Me } from "../api/types";
import ProfilePage from "./ProfilePage";

vi.mock("../api/resources", () => ({ accountApi: {
  me: vi.fn(), updateProfile: vi.fn(), uploadAvatar: vi.fn(), timeZones: vi.fn(),
  requestEmailChange: vi.fn(), confirmEmailChange: vi.fn(),
} }));

const me: Me = {
  user: { id: "profile-test", display_name: "Alex Morgan" }, email: "alex@example.com",
  profile: { email: "alex@example.com", display_name: "Alex Morgan", course_code: "LEGACY",
    time_zone: "Australia/Sydney", biography: "Building thoughtful software.", avatar_url: "",
    avatar_image_url: "", updated_at: "2026-09-30T10:00:00Z" },
  permissions: { site_moderator: false },
};
const originalDialogMethods = {
  showModal: Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "showModal"),
  close: Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "close"),
};

describe("ProfilePage", () => {
  let container: HTMLDivElement;
  let root: Root;
  let client: QueryClient;

  beforeEach(() => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    sessionStorage.clear();
    vi.clearAllMocks();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
    client.setQueryData(["time-zones"], { count: 3, results: [
      { value: "Australia/Sydney", label: "(GMT+10:00) Australia/Sydney", offset: "GMT+10:00" },
      { value: "Asia/Tokyo", label: "(GMT+09:00) Asia/Tokyo", offset: "GMT+09:00" },
      { value: "Europe/London", label: "(GMT+01:00) Europe/London", offset: "GMT+01:00" },
    ] });
    vi.mocked(accountApi.me).mockResolvedValue(me);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    client.clear();
    container.remove();
    sessionStorage.clear();
    vi.restoreAllMocks();
    for (const method of ["showModal", "close"] as const) {
      const original = originalDialogMethods[method];
      if (original) Object.defineProperty(HTMLDialogElement.prototype, method, original);
      else Reflect.deleteProperty(HTMLDialogElement.prototype, method);
    }
  });

  async function render(value = me) {
    client.setQueryData(["me"], value);
    await act(async () => root.render(<QueryClientProvider client={client}><ProfilePage /></QueryClientProvider>));
  }

  function mockDialog() {
    Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function (this: HTMLDialogElement) { this.setAttribute("open", ""); } });
    Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function (this: HTMLDialogElement) { this.removeAttribute("open"); } });
  }

  async function settle() { await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); }); }

  function setInput(input: HTMLInputElement | HTMLTextAreaElement, value: string) {
    const prototype = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value")?.set?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }

  it("renders identity, dedicated security actions and no legacy email/course fields", async () => {
    await render();
    expect(container.textContent).toContain("Alex Morgan");
    expect(container.textContent).toContain("Account & security");
    expect(container.textContent).toContain("On your time");
    expect(container.querySelector('[name="email"]')).toBeNull();
    expect(container.querySelector('[name="course_code"]')).toBeNull();
    expect(container.querySelector('button[aria-label="Change profile photo"]')).not.toBeNull();
    expect(container.querySelector<HTMLButtonElement>('.profile-form button[type="submit"]')?.disabled).toBe(true);
  });

  it("tracks draft changes and saves only the three editable profile attributes", async () => {
    client.setQueryData(["memberships", "project-a"], { count: 0, results: [] });
    vi.mocked(accountApi.updateProfile).mockImplementation(async (patch) => {
      const updated = { ...me.profile, ...patch };
      vi.mocked(accountApi.me).mockResolvedValue({ ...me, profile: updated });
      return updated;
    });
    await render();
    const name = container.querySelector<HTMLInputElement>('[name="display_name"]')!;
    const bio = container.querySelector<HTMLTextAreaElement>('[name="biography"]')!;
    await act(async () => { setInput(name, "Alex Chen"); setInput(bio, "Teamwork."); });
    expect(container.textContent).toContain("Unsaved changes");
    expect(container.textContent).toContain("9 / 500");
    await act(async () => container.querySelector(".profile-form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(vi.mocked(accountApi.updateProfile).mock.calls[0]?.[0]).toEqual({ display_name: "Alex Chen", biography: "Teamwork.", time_zone: "Australia/Sydney" });
    expect(container.textContent).toContain("Profile saved.");
    expect(container.textContent).toContain("Up to date");
    expect(client.getQueryState(["memberships", "project-a"])?.isInvalidated).toBe(true);
  });

  it("refreshes identity and every cached Team list after uploading a replacement photo", async () => {
    const profile = { ...me.profile, avatar_image_url: "/api/v1/users/profile-test/avatar/", updated_at: "2026-10-01T10:00:00Z" };
    client.setQueryData(["memberships", "project-a"], { count: 0, results: [] });
    client.setQueryData(["memberships", "project-b"], { count: 0, results: [] });
    vi.mocked(accountApi.uploadAvatar).mockResolvedValue(profile);
    vi.mocked(accountApi.me).mockResolvedValue({ ...me, profile });
    await render();
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    const photo = new File(["photo"], "photo.png", { type: "image/png" });
    Object.defineProperty(input, "files", { configurable: true, value: [photo] });
    await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
    await settle();
    expect(vi.mocked(accountApi.uploadAvatar).mock.calls[0]?.[0]).toBe(photo);
    expect(container.querySelector(".profile-avatar__image img")?.getAttribute("src")).toBe("/api/v1/users/profile-test/avatar/?v=2026-10-01T10%3A00%3A00Z");
    expect(client.getQueryState(["memberships", "project-a"])?.isInvalidated).toBe(true);
    expect(client.getQueryState(["memberships", "project-b"])?.isInvalidated).toBe(true);
    expect(container.textContent).toContain("Photo updated.");
  });

  it("keeps Team caches and the current avatar unchanged after a failed upload", async () => {
    client.setQueryData(["memberships", "project-a"], { count: 0, results: [] });
    vi.mocked(accountApi.uploadAvatar).mockRejectedValue(new Error("Choose a valid image."));
    await render();
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    Object.defineProperty(input, "files", { configurable: true, value: [new File(["bad"], "bad.png", { type: "image/png" })] });
    await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
    await settle();
    expect(container.querySelector(".profile-avatar__image img")).toBeNull();
    expect(client.getQueryState(["memberships", "project-a"])?.isInvalidated).toBe(false);
    expect(container.textContent).toContain("Choose a valid image.");
  });

  it("keeps global time-zone options out of the tab sequence and supports keyboard selection", async () => {
    await render();
    const input = container.querySelector<HTMLInputElement>('[role="combobox"]')!;
    await act(async () => input.focus());
    const options = [...container.querySelectorAll<HTMLButtonElement>('[role="option"]')];
    expect(options).toHaveLength(3);
    expect(options.every((option) => option.tabIndex === -1)).toBe(true);
    await act(async () => input.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true })));
    await act(async () => input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
    expect(input.value).toContain("Asia/Tokyo");
    expect(input.getAttribute("aria-expanded")).toBe("false");
  });

  it("reopens the selected time zone on click without requiring the input to lose focus", async () => {
    await render();
    const input = container.querySelector<HTMLInputElement>('[role="combobox"]')!;
    await act(async () => input.focus());
    await act(async () => input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
    expect(input.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(input);
    await act(async () => input.click());
    expect(input.getAttribute("aria-expanded")).toBe("true");
    expect(container.querySelectorAll('[role="option"]')).toHaveLength(3);
  });

  it("does not clear an active time-zone search when the open input is clicked", async () => {
    await render();
    const input = container.querySelector<HTMLInputElement>('[role="combobox"]')!;
    await act(async () => { input.focus(); setInput(input, "Tokyo"); });
    await act(async () => input.click());
    expect(input.value).toBe("Tokyo");
    expect(container.querySelectorAll('[role="option"]')).toHaveLength(1);
  });

  it("closes the menu after choosing an option that has received focus", async () => {
    await render();
    const input = container.querySelector<HTMLInputElement>('[role="combobox"]')!;
    await act(async () => input.focus());
    const option = [...container.querySelectorAll<HTMLButtonElement>('[role="option"]')].find((element) => element.textContent?.includes("Asia/Tokyo"))!;
    await act(async () => option.focus());
    await act(async () => option.click());
    expect(document.activeElement).toBe(input);
    expect(input.value).toContain("Asia/Tokyo");
    expect(input.getAttribute("aria-expanded")).toBe("false");
  });

  it("does not submit the profile when Enter is pressed on an empty time-zone search", async () => {
    await render();
    const input = container.querySelector<HTMLInputElement>('[role="combobox"]')!;
    await act(async () => { input.focus(); setInput(input, "not-a-city"); });
    const event = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
    await act(async () => input.dispatchEvent(event));
    expect(event.defaultPrevented).toBe(true);
    expect(accountApi.updateProfile).not.toHaveBeenCalled();
    expect(container.textContent).toContain("No matching time zones.");
  });

  it("keeps profile editing available when the browser cannot format a valid server time zone", async () => {
    await render({ ...me, profile: { ...me.profile, time_zone: "Factory" } });
    expect(container.textContent).toContain("Local time is unavailable in this browser.");
    expect(container.querySelector('[name="display_name"]')).not.toBeNull();
  });

  it("opens changing email in the existing accessible floating dialog", async () => {
    mockDialog();
    await render();
    await act(async () => [...container.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === "Change email")!.click());
    const dialog = container.querySelector<HTMLDialogElement>("dialog")!;
    expect(dialog.open).toBe(true);
    expect(dialog.textContent).toContain("Change sign-in email");
    expect(dialog.querySelector('[name="new_email"]')).not.toBeNull();
    await act(async () => dialog.querySelector<HTMLButtonElement>('[aria-label="Close Change sign-in email"]')!.click());
    expect(dialog.classList.contains("floating-panel--closing")).toBe(true);
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 200)); });
    expect(container.querySelector("dialog")).toBeNull();
  });

  it("links server field feedback to the invalid input and focuses it", async () => {
    vi.mocked(accountApi.updateProfile).mockRejectedValue(new APIError(400, { error: {
      fields: { display_name: ["This name is not allowed."] }, message: "Invalid profile.",
    } }));
    await render();
    const input = container.querySelector<HTMLInputElement>('[name="display_name"]')!;
    await act(async () => setInput(input, "Changed name"));
    await act(async () => container.querySelector(".profile-form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    await settle();
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(document.getElementById(input.getAttribute("aria-describedby")!)?.textContent).toBe("This name is not allowed.");
    expect(document.activeElement).toBe(input);
    expect(container.textContent).toContain("Please check the highlighted details.");
    await act(async () => setInput(input, "Corrected name"));
    expect(input.hasAttribute("aria-invalid")).toBe(false);
  });

  it("protects an unsaved email form and keeps password whitespace unchanged", async () => {
    mockDialog();
    vi.mocked(accountApi.requestEmailChange).mockImplementation(() => new Promise(() => {}));
    await render();
    await act(async () => [...container.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === "Change email")!.click());
    const dialog = container.querySelector<HTMLDialogElement>("dialog")!;
    await act(async () => {
      setInput(dialog.querySelector<HTMLInputElement>('[name="new_email"]')!, "new@example.com");
      setInput(dialog.querySelector<HTMLInputElement>('[name="current_password"]')!, " private key ");
    });
    const close = dialog.querySelector<HTMLButtonElement>('[aria-label="Close Change sign-in email"]')!;
    await act(async () => close.click());
    expect(dialog.textContent).toContain("Discard unsaved changes?");
    await act(async () => [...dialog.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === "Keep editing")!.click());
    await act(async () => dialog.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    await settle();
    expect(accountApi.requestEmailChange).toHaveBeenCalledWith({ new_email: "new@example.com", current_password: " private key " }, expect.anything());
    expect(close.disabled).toBe(true);
    await act(async () => dialog.dispatchEvent(new Event("cancel", { cancelable: true })));
    expect(dialog.open).toBe(true);
  });
});
