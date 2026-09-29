import { describe, expect, it } from "vitest";
import type { MemberInsight } from "../api/types";
import { activityBarPercentage, buildContributionDashboard } from "./contributionInsights";

const members: MemberInsight[] = [
  {
    user_id: "member-b",
    display_name: "Blair",
    role: "member",
    total_events: 3,
    completed_tasks: 1,
    comments: 2,
    accepted_meetings: 0,
  },
  {
    user_id: "member-a",
    display_name: "Alex",
    role: "owner",
    total_events: 6,
    completed_tasks: 2,
    comments: 1,
    accepted_meetings: 4,
  },
];

describe("contribution dashboard calculations", () => {
  it("adds each factual measure independently", () => {
    expect(buildContributionDashboard(members).totals).toEqual({
      recordedActions: 9,
      completedTasks: 3,
      comments: 3,
      acceptedMeetings: 4,
    });
  });

  it("scales activity bars against the highest displayed action count", () => {
    const dashboard = buildContributionDashboard(members);

    expect(dashboard.highestRecordedActions).toBe(6);
    expect(dashboard.memberActivity.map(({ member, percentage }) => [member.display_name, percentage])).toEqual([
      ["Blair", 50],
      ["Alex", 100],
    ]);
  });

  it("preserves the API member order instead of creating a ranking", () => {
    const dashboard = buildContributionDashboard(members);

    expect(dashboard.memberActivity.map(({ member }) => member.user_id)).toEqual([
      "member-b",
      "member-a",
    ]);
    expect(members.map(({ user_id }) => user_id)).toEqual(["member-b", "member-a"]);
  });

  it("handles an empty or all-zero result without dividing by zero", () => {
    const zeroMember = { ...members[0], total_events: 0 } as MemberInsight;

    expect(buildContributionDashboard([])).toEqual({
      totals: {
        recordedActions: 0,
        completedTasks: 0,
        comments: 0,
        acceptedMeetings: 0,
      },
      highestRecordedActions: 0,
      memberActivity: [],
    });
    expect(buildContributionDashboard([zeroMember]).memberActivity[0]?.percentage).toBe(0);
    expect(activityBarPercentage(1, 0)).toBe(0);
  });

  it("bounds visual percentages defensively", () => {
    expect(activityBarPercentage(-1, 10)).toBe(0);
    expect(activityBarPercentage(12, 10)).toBe(100);
  });
});
