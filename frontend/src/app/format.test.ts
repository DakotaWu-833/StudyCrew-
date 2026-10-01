import { afterEach, describe, expect, it, vi } from "vitest";
import { earliestMeetingDateTime, formatDate, meetingDateTimeLimit, parseOptionalDateTime, titleCase, toDateTimeLocal, today } from "./format";

describe("workspace formatting", () => {
  afterEach(() => {
    delete document.documentElement.dataset.timeZone;
    vi.useRealTimers();
  });

  it("uses explicit fallbacks for absent or invalid dates", () => {
    expect(formatDate(null)).toBe("No date set");
    expect(formatDate("not-a-date")).toBe("Invalid date");
    expect(toDateTimeLocal("invalid")).toBe("");
  });

  it("turns valid local form values into UTC ISO values", () => {
    document.documentElement.dataset.timeZone = "Australia/Sydney";
    expect(parseOptionalDateTime("2026-09-14T12:30")).toBe("2026-09-14T02:30:00.000Z");
    expect(parseOptionalDateTime("2026-12-15T12:30")).toBe("2026-12-15T01:30:00.000Z");
    expect(parseOptionalDateTime("")).toBeNull();
  });

  it("round-trips datetime controls in the profile timezone", () => {
    document.documentElement.dataset.timeZone = "Australia/Sydney";
    const localValue = toDateTimeLocal("2026-09-14T02:30:00Z");
    expect(localValue).toBe("2026-09-14T12:30");
    expect(parseOptionalDateTime(localValue)).toBe("2026-09-14T02:30:00.000Z");
  });

  it("rejects impossible dates and daylight-saving gaps", () => {
    document.documentElement.dataset.timeZone = "Australia/Sydney";
    expect(parseOptionalDateTime("2026-02-30T12:00")).toBeUndefined();
    expect(parseOptionalDateTime("2026-10-04T02:30")).toBeUndefined();
  });

  it("formats machine values as readable titles", () => {
    expect(titleCase("task_status_changed")).toBe("Task Status Changed");
  });

  it("keeps the English interface date format independent of the host locale", () => {
    document.documentElement.dataset.timeZone = "Australia/Sydney";
    expect(formatDate("2026-09-14T02:30:00Z")).toBe("14 Sept 2026, 12:30 pm");
  });

  it("returns ISO calendar dates for relative day helpers", () => {
    document.documentElement.dataset.timeZone = "Pacific/Auckland";
    expect(today()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    const start = new Date(`${today()}T00:00:00`);
    const previous = new Date(`${today(-1)}T00:00:00`);
    expect(start.getTime() - previous.getTime()).toBeGreaterThanOrEqual(23 * 60 * 60 * 1000);
  });

  it("uses the profile timezone when the calendar date differs from the host", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T11:30:00Z"));
    document.documentElement.dataset.timeZone = "Pacific/Kiritimati";

    expect(today()).toBe("2026-01-02");
  });

  it("sets the earliest meeting input to the beginning of today in the profile timezone", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T11:30:00Z"));
    document.documentElement.dataset.timeZone = "Pacific/Kiritimati";

    expect(earliestMeetingDateTime()).toBe("2026-01-02T00:00");
  });

  it("uses an inclusive ten-calendar-year meeting limit and contracts leap day", () => {
    document.documentElement.dataset.timeZone = "UTC";
    expect(meetingDateTimeLimit(new Date("2028-02-29T09:45:00Z"))).toBe("2038-02-28T09:45");
    expect(meetingDateTimeLimit(new Date("2026-09-20T13:05:00Z"))).toBe("2036-09-20T13:05");
  });

  it("uses the server's UTC horizon when Sydney daylight saving differs ten years later", () => {
    document.documentElement.dataset.timeZone = "Australia/Sydney";
    expect(meetingDateTimeLimit(new Date("2026-10-03T17:30:00Z"))).toBe("2036-10-04T03:30");
  });
});
