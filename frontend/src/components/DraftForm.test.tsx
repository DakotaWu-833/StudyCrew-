import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DraftForm from "./DraftForm";
import { clearUserDrafts, draftKey, draftLifetime, loadDraft, saveDraft } from "../app/drafts";
vi.mock("../api/resources", () => ({ accountApi: { me: vi.fn() } }));

describe("local draft privacy and recovery", () => {
  let root: Root, container: HTMLDivElement, client: QueryClient;
  beforeEach(() => { Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); localStorage.clear(); container = document.createElement("div"); document.body.append(container); root = createRoot(container); client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } }); client.setQueryData(["me"], { user: { id: "student-a" } }); });
  afterEach(async () => { await act(async () => root.unmount()); client.clear(); container.remove(); localStorage.clear(); });
  async function render() { await act(async () => root.render(<QueryClientProvider client={client}><DraftForm scope="team-1:minutes" fields={["minutes", "password"]} onSubmit={event => event.preventDefault()}><textarea name="minutes" defaultValue="Server version" /><input name="password" type="password" /><button type="reset">Saved successfully</button></DraftForm></QueryClientProvider>)); }
  async function fill(value: string) { const input = container.querySelector("textarea")!; await act(async () => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); }); }
  it("recovers unsent text into the actual form and clears it only after a successful reset", async () => {
    saveDraft("student-a", "team-1:minutes", { minutes: "Unsent meeting notes" }); await render();
    const restore = [...container.querySelectorAll("button")].find(button => button.textContent === "Restore draft")!;
    await act(async () => restore.click()); expect(new FormData(container.querySelector("form")!).get("minutes")).toBe("Unsent meeting notes");
    await fill("Revised notes after reconnecting"); expect(loadDraft("student-a", "team-1:minutes")?.values.minutes).toBe("Revised notes after reconnecting");
    await act(async () => container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(loadDraft("student-a", "team-1:minutes")).not.toBeNull();
    await act(async () => container.querySelector("form")!.reset()); expect(loadDraft("student-a", "team-1:minutes")).toBeNull();
  });
  it("excludes credentials and isolates drafts by account and form", async () => {
    await render(); container.querySelector("input")!.value = "Secret credential"; await fill("A private note");
    expect(loadDraft("student-a", "team-1:minutes")?.values).toEqual({ minutes: "A private note" });
    expect(loadDraft("student-b", "team-1:minutes")).toBeNull(); expect(loadDraft("student-a", "team-2:minutes")).toBeNull();
    saveDraft("student-b", "team-1:minutes", { minutes: "Other user" }); clearUserDrafts("student-a");
    expect(loadDraft("student-a", "team-1:minutes")).toBeNull(); expect(loadDraft("student-b", "team-1:minutes")?.values.minutes).toBe("Other user");
  });
  it("expires old drafts before presenting a restore action", async () => {
    localStorage.setItem(draftKey("student-a", "team-1:minutes"), JSON.stringify({ savedAt: Date.now() - draftLifetime - 1, values: { minutes: "Expired note" } }));
    await render(); expect(container.textContent).not.toContain("Restore draft"); expect(localStorage.getItem(draftKey("student-a", "team-1:minutes"))).toBeNull();
  });
});
