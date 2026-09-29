import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { InsightsCharts, MemberInsight } from "../api/types";
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

const charts: InsightsCharts = {
  task_status: [
    { key: "todo", label: "To do", count: 2 },
    { key: "in_progress", label: "In progress", count: 1 },
    { key: "blocked", label: "Blocked", count: 0 },
    { key: "done", label: "Done", count: 3 },
  ],
  task_priority: [
    { key: "low", label: "Low", count: 0 },
    { key: "medium", label: "Medium", count: 4 },
    { key: "high", label: "High", count: 2 },
    { key: "urgent", label: "Urgent", count: 0 },
  ],
  task_assignees: [{ key: "member-1", label: "Alex Morgan", count: 2 }, { key: "unassigned", label: "Unassigned", count: 1 }],
  tasks_created: [{ date: "2026-08-01", count: 2 }, { date: "2026-08-02", count: 0 }],
  completion_cycle: [
    { date: "2026-08-01", count: 1, average_hours: 2.5 },
    { date: "2026-08-02", count: 0, average_hours: null },
  ],
};

const renderDashboard = (members: MemberInsight[], eventType = "") => renderToStaticMarkup(
  <ContributionDashboard
    members={members}
    rangeStart="2026-08-01"
    rangeEnd="2026-08-31"
    eventType={eventType}
    charts={charts}
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

  it("renders the distribution and trend visualisations from factual chart data", () => {
    const markup = renderDashboard([member]);

    expect(markup).toContain("Work items by status");
    expect(markup).toContain("Work items by priority");
    expect(markup).toContain("Open work by assignee");
    expect(markup).toContain("Work item creation trend");
    expect(markup).toContain("Work item cycle time");
    expect(markup).toContain('aria-label="Work items by status: 6 tasks"');
    expect(markup).toContain('aria-label="Open work by assignee: 3 assignments"');
    expect(markup).toContain("task assigned to multiple people appears for each assignee");
    expect(markup).toContain("does not currently record a separate task type");
    expect(markup).toContain("2.5 hours across 1 completed task");
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
