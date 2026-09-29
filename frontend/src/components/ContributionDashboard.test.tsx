import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { MemberInsight } from "../api/types";
import ContributionDashboard from "./ContributionDashboard";

const member: MemberInsight = {
  user_id: "member-1",
  display_name: "Alex Morgan",
  role: "owner",
  total_events: 5,
  completed_tasks: 2,
  comments: 3,
  accepted_meetings: 1,
};

const renderDashboard = (members: MemberInsight[], eventType = "") => renderToStaticMarkup(
  <ContributionDashboard
    members={members}
    rangeStart="2026-08-01"
    rangeEnd="2026-08-31"
    eventType={eventType}
  />,
);

describe("ContributionDashboard", () => {
  it("renders exact totals and an accessible visual activity list", () => {
    const markup = renderDashboard([member]);

    expect(markup).toContain("Contribution snapshot");
    expect(markup).toContain("Tasks completed");
    expect(markup).toContain("Meetings accepted");
    expect(markup).toContain("Alex Morgan");
    expect(markup).toContain('aria-label="5 recorded actions"');
    expect(markup).toContain('aria-hidden="true"');
    expect(markup).toContain("not a score");
  });

  it("states that an activity filter applies only to recorded actions and the timeline", () => {
    const markup = renderDashboard([member], "task_status_changed");

    expect(markup).toContain("Filtered by Task Status Changed");
    expect(markup).toContain("The activity filter applies only to");
    expect(markup).toContain("other totals remain stable facts");
  });

  it("keeps zero-activity members visible with a clear zero state", () => {
    const markup = renderDashboard([{ ...member, total_events: 0 }]);

    expect(markup).toContain("No recorded actions match the selected activity scope and date range");
    expect(markup).toContain("Alex Morgan");
    expect(markup).toContain('aria-label="0 recorded actions"');
    expect(markup).toContain("width:0%");
  });

  it("explains the genuinely empty membership state", () => {
    const markup = renderDashboard([]);

    expect(markup).toContain("No current members are available for this snapshot.");
    expect(markup).not.toContain("No recorded actions match the selected activity scope");
  });
});
