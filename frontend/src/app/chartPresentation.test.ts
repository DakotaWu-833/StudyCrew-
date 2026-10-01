import { describe, expect, it } from "vitest";
import { countAxisTicks, cycleAxisScale, distributionColour, formatCycleDuration, formatCycleNumber } from "./chartPresentation";

describe("factual chart presentation", () => {
  it("never repeats count ticks or presents fractional task counts", () => {
    for (const maximum of [0, 1, 2, 3, 5, 17]) {
      const ticks = countAxisTicks(maximum);
      expect(new Set(ticks).size).toBe(ticks.length);
      expect(ticks.every(Number.isInteger)).toBe(true);
      expect(ticks[0]).toBe(0);
      expect(ticks.at(-1)).toBe(Math.max(1, maximum));
    }
    expect(countAxisTicks(1)).toEqual([0, 1]);
  });

  it("uses minutes and seconds instead of rounding short cycles to zero hours", () => {
    expect(formatCycleDuration(0.5)).toBe("30 minutes");
    expect(formatCycleDuration(1 / 120)).toBe("30 seconds");
    expect(formatCycleDuration(2.5)).toBe("2.5 hours");
    expect(cycleAxisScale(0).label).toBe("minutes");
    expect(formatCycleNumber(0.0036)).toBe("0.0036");
  });

  it("keeps meaning and member colours stable independent of response order", () => {
    expect(distributionColour("done", "status")).toBe("#27866f");
    expect(distributionColour("blocked", "status")).toBe("#bc4455");
    expect(distributionColour("urgent", "priority")).toBe("#bc4455");
    expect(distributionColour("member-1", "assignee")).toBe(distributionColour("member-1", "assignee"));
    expect(distributionColour("unassigned", "assignee")).toBe("#748399");
  });
});
