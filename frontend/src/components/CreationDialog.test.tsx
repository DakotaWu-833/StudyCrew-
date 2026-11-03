import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import CreationDialog from "./CreationDialog";
import { openCreation } from "../../tests/dialogs";

let root: Root, container: HTMLDivElement;
const submit = vi.fn(), outerSubmit = vi.fn();
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.clearAllMocks(); vi.stubGlobal("matchMedia", () => ({ matches: true }));
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.unstubAllGlobals(); });

async function render({ busy = false, completedKey = 0, error = undefined as unknown, disabled = false, nested = false } = {}) {
  const panel = <CreationDialog title="Add a course" triggerLabel="Add course" busy={busy} completedKey={completedKey} error={error} disabled={disabled}>
    <form onSubmit={event => { event.preventDefault(); submit(new FormData(event.currentTarget).get("name")); }}>
      <label>Course name<input name="name" required /></label><button type="submit">Save course</button>
    </form>
  </CreationDialog>;
  await act(async () => root.render(nested ? <form onSubmit={event => { event.preventDefault(); outerSubmit(); }}>{panel}</form> : panel));
}
async function click(label: string) { await openCreation(label); }
async function type(value: string) {
  const input = document.body.querySelector<HTMLInputElement>('dialog input[name="name"]')!;
  await act(async () => { input.value = value; input.dispatchEvent(new Event("input", { bubbles: true })); });
}

it("shows only the creation trigger until clicked and uses the shared named modal", async () => {
  await render(); expect(document.body.querySelector("dialog")).toBeNull();
  await click("Add course");
  const dialog = document.body.querySelector("dialog")!;
  expect(dialog.open).toBe(true); expect(dialog.querySelector("h2")?.textContent).toBe("Add a course");
  expect(dialog.parentElement).toBe(document.body);
});

it("guards cancel, Escape and backdrop closure without losing entered values", async () => {
  await render(); await click("Add course"); await type("Software engineering");
  await click("Cancel"); expect(document.body.textContent).toContain("Discard unsaved changes?");
  await click("Keep editing");
  await act(async () => document.body.querySelector("dialog")!.dispatchEvent(new Event("cancel", { cancelable: true })));
  expect(document.body.textContent).toContain("Discard unsaved changes?");
  await click("Keep editing");
  await act(async () => document.body.querySelector("dialog")!.click());
  expect(document.body.querySelector<HTMLInputElement>("dialog input")!.value).toBe("Software engineering");
  await click("Discard changes"); expect(document.body.querySelector("dialog")).toBeNull();
  expect(document.activeElement?.textContent).toBe("Add course");
});

it("retains a failed submission, closes on fresh success, and reopens without stale success closing it", async () => {
  await render(); await click("Add course"); await type("Keep this input");
  await render({ error: new Error("Please retry"), completedKey: 0 });
  expect(document.body.querySelector<HTMLInputElement>("dialog input")!.value).toBe("Keep this input");
  expect(document.body.querySelector('[role="alert"]')?.textContent).toContain("Please retry");
  await render({ completedKey: 1 }); expect(document.body.querySelector("dialog")).toBeNull();
  await click("Add course"); expect(document.body.querySelector<HTMLInputElement>("dialog input")!.value).toBe("");
  await type("Second course"); await render({ completedKey: 2 }); expect(document.body.querySelector("dialog")).toBeNull();
});

it("blocks closing, field edits and duplicate submission while saving", async () => {
  await render(); await click("Add course"); await type("Pending course");
  await render({ busy: true });
  expect(document.body.querySelector<HTMLFieldSetElement>("dialog fieldset")!.disabled).toBe(true);
  expect(document.body.querySelector<HTMLButtonElement>('button[aria-label="Close Add a course"]')!.disabled).toBe(true);
  await act(async () => {
    document.body.querySelector("dialog form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    document.body.querySelector("dialog")!.dispatchEvent(new Event("cancel", { cancelable: true }));
  });
  expect(submit).not.toHaveBeenCalled(); expect(document.body.querySelector("dialog")!.open).toBe(true);
});

it("keeps nested creation steps out of the parent form and stops a child submit from publishing the parent", async () => {
  await render({ nested: true }); await click("Add course"); await type("Child record");
  expect(document.body.querySelector("form form")).toBeNull();
  await act(async () => document.body.querySelector("dialog form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(submit).toHaveBeenCalledWith("Child record"); expect(outerSubmit).not.toHaveBeenCalled();
});

it("keeps disabled creation controls from opening a modal", async () => {
  await render({ disabled: true }); await click("Add course");
  expect(document.body.querySelector("dialog")).toBeNull();
});

it("closes only the top creation step when Escape is used in a nested modal", async () => {
  await act(async () => root.render(<CreationDialog title="Create a poll" triggerLabel="New poll">
    <CreationDialog title="Add candidate" triggerLabel="Add candidate"><input aria-label="Candidate time" /></CreationDialog>
  </CreationDialog>));
  await click("New poll"); await click("Add candidate");
  expect(document.body.querySelectorAll("dialog")).toHaveLength(2);
  await act(async () => [...document.body.querySelectorAll("dialog")].at(-1)!.dispatchEvent(new Event("cancel", { cancelable: true })));
  expect(document.body.querySelectorAll("dialog")).toHaveLength(1);
  expect(document.body.querySelector("dialog h2")?.textContent).toBe("Create a poll");
});
