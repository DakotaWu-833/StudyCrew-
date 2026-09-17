import { afterEach, describe, expect, it, vi } from "vitest";
import { scheduleDebounced } from "./debounce";

describe("scheduleDebounced", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("runs a search update only after 300 milliseconds", () => {
    vi.useFakeTimers();
    const callback = vi.fn();
    scheduleDebounced(callback);

    vi.advanceTimersByTime(299);
    expect(callback).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(callback).toHaveBeenCalledOnce();
  });

  it("cancels the pending update when the search value changes", () => {
    vi.useFakeTimers();
    const callback = vi.fn();
    const cancel = scheduleDebounced(callback);
    cancel();
    vi.advanceTimersByTime(300);
    expect(callback).not.toHaveBeenCalled();
  });
});
