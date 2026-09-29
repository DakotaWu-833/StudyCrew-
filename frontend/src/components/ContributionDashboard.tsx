import type { MemberInsight } from "../api/types";
import { buildContributionDashboard } from "../app/contributionInsights";
import { titleCase } from "../app/format";
import { Panel, StatusBadge } from "./UI";

interface ContributionDashboardProps {
  members: MemberInsight[];
  rangeStart: string;
  rangeEnd: string;
  eventType: string;
}

const pluralise = (value: number, singular: string) =>
  `${value} ${value === 1 ? singular : `${singular}s`}`;

export default function ContributionDashboard({
  members,
  rangeStart,
  rangeEnd,
  eventType,
}: ContributionDashboardProps) {
  const dashboard = buildContributionDashboard(members);
  const activityScope = eventType ? titleCase(eventType) : "All activity types";

  return (
    <Panel className="contribution-dashboard" labelledBy="contribution-dashboard-heading">
      <div className="section-heading contribution-dashboard__heading">
        <div>
          <h3 id="contribution-dashboard-heading">Contribution snapshot</h3>
          <p>Current members · {rangeStart} to {rangeEnd}</p>
        </div>
        <span>{activityScope}</span>
      </div>

      <ul className="insight-summary-grid" aria-label="Factual totals for current members">
        <li className="insight-stat insight-stat--actions">
          <span className="insight-stat__label">Recorded actions</span>
          <strong>{dashboard.totals.recordedActions}</strong>
          <small>{eventType ? `Filtered by ${titleCase(eventType)}` : "All recorded activity types"}</small>
        </li>
        <li className="insight-stat insight-stat--tasks">
          <span className="insight-stat__label">Tasks completed</span>
          <strong>{dashboard.totals.completedTasks}</strong>
          <small>Unique tasks moved to done</small>
        </li>
        <li className="insight-stat insight-stat--comments">
          <span className="insight-stat__label">Comments</span>
          <strong>{dashboard.totals.comments}</strong>
          <small>Comments created</small>
        </li>
        <li className="insight-stat insight-stat--meetings">
          <span className="insight-stat__label">Meetings accepted</span>
          <strong>{dashboard.totals.acceptedMeetings}</strong>
          <small>Accepted meetings scheduled</small>
        </li>
      </ul>

      <p className="contribution-dashboard__note">
        These measures can overlap and are factual counts, not a score. The activity filter applies only to
        Recorded actions and the timeline; the other totals remain stable facts for the selected dates.
      </p>

      <figure className="member-activity-chart" aria-labelledby="member-activity-heading">
        <figcaption className="member-activity-chart__caption">
          <div>
            <h4 id="member-activity-heading">Recorded actions by current member</h4>
            <p>Bar length is relative to the highest displayed count and does not rank contribution quality.</p>
          </div>
          <span>{activityScope}</span>
        </figcaption>

        {dashboard.memberActivity.length > 0 && dashboard.highestRecordedActions === 0 && (
          <p className="member-activity-chart__zero" role="status">
            No recorded actions match the selected activity scope and date range. Current members remain visible with zero counts.
          </p>
        )}

        {dashboard.memberActivity.length > 0 ? (
          <ol className="member-activity-list">
            {dashboard.memberActivity.map(({ member, percentage }) => (
              <li className="member-activity-row" key={member.user_id}>
                <span className="member-activity-row__member">
                  <strong>{member.display_name}</strong>
                  <StatusBadge value={member.role} />
                </span>
                <span className="member-activity-track" aria-hidden="true">
                  <span className="member-activity-track__fill" style={{ width: `${percentage}%` }} />
                </span>
                <span
                  className="member-activity-row__value"
                  aria-label={pluralise(member.total_events, "recorded action")}
                >
                  {member.total_events}
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="member-activity-chart__zero" role="status">No current members are available for this snapshot.</p>
        )}
      </figure>
    </Panel>
  );
}
