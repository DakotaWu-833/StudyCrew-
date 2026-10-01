import { act, createRef, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Button, ErrorState, Field, FloatingPanel, Loading, useFieldControl } from "./UI";

const originalDialogMethods = {
  showModal: Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "showModal"),
  close: Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "close"),
};

describe("shared interface feedback", () => {
  let container: HTMLDivElement;
  let root: Root;
  let opener: HTMLButtonElement;
  const onDismiss = vi.fn();

  beforeEach(() => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    vi.useFakeTimers();
    onDismiss.mockClear();
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: false }));
    Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function (this: HTMLDialogElement) {
      this.setAttribute("open", "");
      this.querySelector<HTMLElement>("input, button")?.focus();
    } });
    Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function (this: HTMLDialogElement) {
      this.removeAttribute("open");
      // Native close events are queued; retaining that behaviour exercises Strict Mode cleanup.
      setTimeout(() => this.dispatchEvent(new Event("close")), 0);
    } });
    opener = document.createElement("button");
    opener.textContent = "Open editor";
    document.body.appendChild(opener);
    opener.focus();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    opener.remove();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    for (const method of ["showModal", "close"] as const) {
      const original = originalDialogMethods[method];
      if (original) Object.defineProperty(HTMLDialogElement.prototype, method, original);
      else Reflect.deleteProperty(HTMLDialogElement.prototype, method);
    }
  });

  async function renderPanel(props: { busy?: boolean; dirty?: boolean } = {}) {
    await act(async () => root.render(<FloatingPanel title="Edit task" onDismiss={onDismiss} {...props}>
      <Field label="Task title"><input name="title" defaultValue="Proposal" /></Field>
    </FloatingPanel>));
    return container.querySelector<HTMLDialogElement>("dialog")!;
  }

  function button(label: string) {
    return [...container.querySelectorAll<HTMLButtonElement>("button")].find((element) => element.textContent === label)!;
  }

  it("keeps the modal open during a short exit and dismisses exactly once with focus restored", async () => {
    const dialog = await renderPanel();
    expect(dialog.open).toBe(true);
    expect(dialog.getAttribute("aria-labelledby")).toBe(dialog.querySelector("h2")?.id);
    await act(async () => {
      const close = dialog.querySelector<HTMLButtonElement>('[aria-label="Close Edit task"]')!;
      close.click();
      close.click();
    });
    expect(dialog.classList.contains("floating-panel--closing")).toBe(true);
    expect(dialog.open).toBe(true);
    expect(onDismiss).not.toHaveBeenCalled();
    await act(async () => vi.advanceTimersByTime(179));
    expect(onDismiss).not.toHaveBeenCalled();
    await act(async () => vi.advanceTimersByTime(1));
    expect(dialog.open).toBe(false);
    expect(document.activeElement).toBe(opener);
    expect(onDismiss).toHaveBeenCalledTimes(1);
    await act(async () => vi.runAllTimers());
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("closes immediately when reduced motion is requested", async () => {
    vi.mocked(window.matchMedia).mockReturnValue({ matches: true } as MediaQueryList);
    const dialog = await renderPanel();
    await act(async () => dialog.querySelector<HTMLButtonElement>('[aria-label="Close Edit task"]')!.click());
    expect(dialog.open).toBe(false);
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("blocks Escape and backdrop dismissal while a request is in progress", async () => {
    const dialog = await renderPanel({ busy: true });
    const cancel = new Event("cancel", { cancelable: true });
    await act(async () => { dialog.dispatchEvent(cancel); dialog.click(); });
    await act(async () => vi.runAllTimers());
    expect(cancel.defaultPrevented).toBe(true);
    expect(dialog.open).toBe(true);
    expect(onDismiss).not.toHaveBeenCalled();
    expect(dialog.getAttribute("aria-busy")).toBe("true");
    expect(dialog.querySelector<HTMLButtonElement>('[aria-label="Close Edit task"]')!.disabled).toBe(true);
    expect(dialog.querySelector('[role="status"]')?.textContent).toContain("Working");
  });

  it("allows Escape to dismiss a clean form", async () => {
    const dialog = await renderPanel();
    await act(async () => dialog.dispatchEvent(new Event("cancel", { cancelable: true })));
    await act(async () => vi.advanceTimersByTime(180));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("asks inline before discarding a dirty form and preserves typed values when editing continues", async () => {
    const dialog = await renderPanel({ dirty: true });
    const input = dialog.querySelector<HTMLInputElement>("input")!;
    input.value = "Unfinished draft";
    input.focus();
    await act(async () => dialog.dispatchEvent(new Event("cancel", { cancelable: true })));
    expect(container.querySelectorAll("dialog")).toHaveLength(1);
    expect(dialog.textContent).toContain("Discard unsaved changes?");
    expect(document.activeElement).toBe(button("Keep editing"));
    expect(onDismiss).not.toHaveBeenCalled();
    await act(async () => button("Keep editing").click());
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe("Unfinished draft");
    expect(dialog.textContent).not.toContain("Discard unsaved changes?");
    await act(async () => dialog.dispatchEvent(new Event("cancel", { cancelable: true })));
    await act(async () => button("Discard changes").click());
    await act(async () => vi.advanceTimersByTime(180));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("clears the discard warning when the same panel advances to a saved phase without stealing focus", async () => {
    const dialog = await renderPanel({ dirty: true });
    await act(async () => dialog.dispatchEvent(new Event("cancel", { cancelable: true })));
    expect(dialog.textContent).toContain("Discard unsaved changes?");
    expect(document.activeElement).toBe(button("Keep editing"));
    const input = dialog.querySelector<HTMLInputElement>("input")!;
    input.focus();
    await renderPanel({ dirty: false });
    expect(container.querySelector("dialog")).toBe(dialog);
    expect(dialog.textContent).not.toContain("Discard unsaved changes?");
    expect(document.activeElement).toBe(input);
    expect(onDismiss).not.toHaveBeenCalled();
    await renderPanel({ dirty: true });
    expect(dialog.textContent).not.toContain("Discard unsaved changes?");
    expect(document.activeElement).toBe(input);
  });

  it("cancels pending exit on unmount without calling stale dismissal handlers", async () => {
    const dialog = await renderPanel();
    await act(async () => dialog.querySelector<HTMLButtonElement>('[aria-label="Close Edit task"]')!.click());
    await act(async () => root.render(null));
    await act(async () => vi.runAllTimers());
    expect(onDismiss).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(opener);
  });

  it("does not dismiss during Strict Mode's effect cleanup and restores focus on actual removal", async () => {
    await act(async () => root.render(<StrictMode><FloatingPanel title="Strict editor" onDismiss={onDismiss}><input name="title" /></FloatingPanel></StrictMode>));
    await act(async () => vi.runAllTimers());
    expect(container.querySelector<HTMLDialogElement>("dialog")?.open).toBe(true);
    expect(onDismiss).not.toHaveBeenCalled();
    await act(async () => root.render(null));
    expect(document.activeElement).toBe(opener);
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it("uses the newest dismiss callback after parent updates", async () => {
    await renderPanel();
    const latestDismiss = vi.fn();
    await act(async () => root.render(<FloatingPanel title="Edit task" onDismiss={latestDismiss}><input /></FloatingPanel>));
    await act(async () => container.querySelector<HTMLButtonElement>('[aria-label="Close Edit task"]')!.click());
    await act(async () => vi.advanceTimersByTime(180));
    expect(latestDismiss).toHaveBeenCalledTimes(1);
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it("links a native field label, hint and error while preserving its props and ref", async () => {
    const ref = createRef<HTMLInputElement>();
    const changed = vi.fn();
    await act(async () => root.render(<Field label="Name" hint="Use your team name." error="At least two characters.">
      <input id="name-input" ref={ref} aria-describedby="external-help" required maxLength={80} defaultValue="A" onInput={changed} />
    </Field>));
    const input = container.querySelector<HTMLInputElement>("input")!;
    expect(ref.current).toBe(input);
    expect(container.querySelector("label")?.htmlFor).toBe("name-input");
    expect(input.getAttribute("aria-describedby")).toBe("external-help name-input-hint name-input-error");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(input.required).toBe(true);
    expect(input.maxLength).toBe(80);
    expect(input.value).toBe("A");
    await act(async () => input.dispatchEvent(new Event("input", { bubbles: true })));
    expect(changed).toHaveBeenCalledTimes(1);
  });

  it("generates independent IDs and removes error associations after correction", async () => {
    await act(async () => root.render(<><Field label="City" error="Choose a city."><select><option>London</option></select></Field><Field label="Bio"><textarea /></Field></>));
    const select = container.querySelector<HTMLSelectElement>("select")!;
    const textarea = container.querySelector<HTMLTextAreaElement>("textarea")!;
    expect(select.id).not.toBe(textarea.id);
    expect(document.getElementById(select.getAttribute("aria-describedby")!)?.textContent).toBe("Choose a city.");
    await act(async () => root.render(<><Field label="City"><select><option>London</option></select></Field><Field label="Bio"><textarea /></Field></>));
    expect(select.getAttribute("aria-invalid")).toBeNull();
    expect(select.getAttribute("aria-describedby")).toBeNull();
  });

  it("lets composite fields attach accessibility attributes to the actual combobox", async () => {
    function CompositePicker() {
      const control = useFieldControl();
      return <div className="picker"><input {...control} role="combobox" aria-expanded="false" /></div>;
    }
    await act(async () => root.render(<Field label="Time zone" hint="Worldwide cities." error="Select a supported zone."><CompositePicker /></Field>));
    const input = container.querySelector<HTMLInputElement>('[role="combobox"]')!;
    expect(container.querySelector("label")?.htmlFor).toBe(input.id);
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(input.getAttribute("aria-describedby")?.split(" ").map((id) => document.getElementById(id)?.textContent)).toEqual(["Worldwide cities.", "Select a supported zone."]);
    expect(container.querySelector(".picker")?.getAttribute("aria-invalid")).toBeNull();
  });

  it("keeps full feedback as default and supports compact feedback and retry", async () => {
    const retry = vi.fn();
    await act(async () => root.render(<><Loading /><Loading size="compact" label="Updating results…" /><ErrorState error={new Error("Try a different search.")} size="compact" retry={retry} /><Button type="button">Action</Button></>));
    expect(container.querySelector(".state-message--full")?.getAttribute("role")).toBe("status");
    expect(container.querySelectorAll(".state-message--compact")).toHaveLength(2);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("Try a different search.");
    await act(async () => button("Try again").click());
    expect(retry).toHaveBeenCalledTimes(1);
  });
});
