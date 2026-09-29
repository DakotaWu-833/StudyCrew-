import type { MemberInsight } from "../api/types";

export interface ContributionTotals {
  recordedActions: number;
  completedTasks: number;
  comments: number;
  acceptedMeetings: number;
}

export interface MemberActivityBar {
  member: MemberInsight;
  percentage: number;
}

export interface ContributionDashboardData {
  totals: ContributionTotals;
  highestRecordedActions: number;
  memberActivity: MemberActivityBar[];
}

export function activityBarPercentage(value: number, highestValue: number): number {
  if (highestValue <= 0 || value <= 0) return 0;
  return Math.round(Math.min(100, (value / highestValue) * 100) * 100) / 100;
}

export function buildContributionDashboard(
  members: readonly MemberInsight[],
): ContributionDashboardData {
  const totals = members.reduce<ContributionTotals>(
    (current, member) => ({
      recordedActions: current.recordedActions + member.total_events,
      completedTasks: current.completedTasks + member.completed_tasks,
      comments: current.comments + member.comments,
      acceptedMeetings: current.acceptedMeetings + member.accepted_meetings,
    }),
    {
      recordedActions: 0,
      completedTasks: 0,
      comments: 0,
      acceptedMeetings: 0,
    },
  );
  const highestRecordedActions = members.reduce(
    (highest, member) => Math.max(highest, member.total_events),
    0,
  );

  return {
    totals,
    highestRecordedActions,
    memberActivity: members.map((member) => ({
      member,
      percentage: activityBarPercentage(member.total_events, highestRecordedActions),
    })),
  };
}
