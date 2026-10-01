import type { ReactNode } from "react";
import type {
  InsightDailyCount,
  InsightDailyCycle,
  InsightDistributionPoint,
  InsightsCharts,
  MemberInsight,
} from "../api/types";
import { buildContributionDashboard } from "../app/contributionInsights";
import { countAxisTicks, cycleAxisScale, distributionColour, formatCycleDuration, formatCycleNumber } from "../app/chartPresentation";
import { titleCase } from "../app/format";
import { Panel, StatusBadge } from "./UI";

interface ContributionDashboardProps {
  members: MemberInsight[];
  rangeStart: string;
  rangeEnd: string;
  eventType: string;
  charts: InsightsCharts;
}

const pluralise = (value: number, singular: string) =>
  `${value} ${value === 1 ? singular : `${singular}s`}`;

export default function ContributionDashboard({
  members,
  rangeStart,
  rangeEnd,
  eventType,
  charts,
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

      <p className="contribution-dashboard__note">Factual counts. Not a score or ranking.</p>
      <details className="contribution-methods">
      <summary>How these statistics work</summary>
      <p>
        These measures can overlap and are factual counts, not a score. The activity filter applies only to
        Recorded actions and the timeline; the other totals remain stable facts for the selected dates.
      </p>
      <p>Current, non-archived tasks are shown in the distribution charts. Trends use the selected dates.</p>
      <p>This project does not currently record a separate task type, so priority is shown instead. Creation history
        includes tasks archived later. Completion time uses tasks still marked done; reopening clears the prior completion time.</p>
      </details>

      <section className="contribution-visuals" aria-labelledby="contribution-visuals-heading">
        <div className="contribution-visuals__heading">
          <div>
            <h4 id="contribution-visuals-heading">Work at a glance</h4>
            <p>Live work. Clear patterns.</p>
          </div>
        </div>
        <div className="contribution-donut-grid">
          <DonutChart title="Work items by status" points={charts.task_status} colourKind="status" />
          <DonutChart title="Work items by priority" points={charts.task_priority} colourKind="priority" />
          <DonutChart
            title="Open work by assignee"
            points={charts.task_assignees}
            colourKind="assignee"
            totalLabel="assignments"
            footnote="Counts are task assignments; a task assigned to multiple people appears for each assignee."
          />
        </div>
        <div className="contribution-trend-grid">
          <TrendChart title="Work item creation trend" subtitle="Tasks created per day" points={charts.tasks_created} />
          <CycleChart points={charts.completion_cycle} />
        </div>
      </section>

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

const ringCircumference = 2 * Math.PI * 45;

function DonutChart({
  title,
  points,
  colourKind,
  totalLabel = "tasks",
  footnote,
}: {
  title: string;
  points: InsightDistributionPoint[];
  colourKind: "status" | "priority" | "assignee";
  totalLabel?: string;
  footnote?: string;
}) {
  const total = points.reduce((sum, point) => sum + point.count, 0);
  let consumed = 0;

  return (
    <figure className="contribution-chart-card">
      <figcaption><h5>{title}</h5></figcaption>
      <div className="contribution-donut-layout">
        <div className="contribution-donut" role="img" aria-label={`${title}: ${total} ${totalLabel}`}>
          <svg viewBox="0 0 180 150" aria-hidden="true" focusable="false">
            <circle className="contribution-donut__track" cx="90" cy="75" r="45" />
            {total > 0 && points.map((point) => {
              const length = (point.count / total) * ringCircumference;
              const offset = consumed;
              consumed += length;
              if (point.count === 0) return null;
              return (
                <circle
                  key={point.key}
                  className="contribution-donut__segment"
                  cx="90"
                  cy="75"
                  r="45"
                  stroke={distributionColour(point.key, colourKind)}
                  strokeDasharray={`${length} ${ringCircumference - length}`}
                  strokeDashoffset={-offset}
                  transform="rotate(-90 90 75)"
                />
              );
            })}
            <text className="contribution-donut__total" x="90" y="73">{total}</text>
            <text className="contribution-donut__label" x="90" y="91">{totalLabel}</text>
          </svg>
        </div>
        <ul className="contribution-chart-legend">
          {points.map((point) => (
            <li key={point.key}>
              <span className="contribution-chart-legend__label">
                <i style={{ backgroundColor: distributionColour(point.key, colourKind) }} aria-hidden="true" />
                <span>{point.label}</span>
              </span>
              <strong>{point.count}</strong>
            </li>
          ))}
        </ul>
      </div>
      {total === 0 && <p className="contribution-chart-card__empty">No work items in this distribution yet.</p>}
      {footnote && <details className="contribution-methods"><summary>About assignments</summary><p className="contribution-chart-card__note">{footnote}</p></details>}
    </figure>
  );
}

const chartWidth = 480;
const chartHeight = 220;
const chartMargin = { top: 20, right: 40, bottom: 40, left: 64 };
const plotWidth = chartWidth - chartMargin.left - chartMargin.right;
const plotHeight = chartHeight - chartMargin.top - chartMargin.bottom;

function TrendFrame({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  return (
    <figure className="contribution-chart-card contribution-trend-card">
      <figcaption>
        <h5>{title}</h5>
        <p>{subtitle}</p>
      </figcaption>
      {children}
    </figure>
  );
}

function dateLabel(value: string) {
  return value.slice(5);
}

function TrendChart({
  title,
  subtitle,
  points,
}: {
  title: string;
  subtitle: string;
  points: InsightDailyCount[];
}) {
  const maximum = Math.max(0, ...points.map((point) => point.count));
  const baseline = chartMargin.top + plotHeight;
  const step = points.length > 0 ? plotWidth / points.length : plotWidth;
  const barWidth = Math.max(1, Math.min(15, step * 0.76));
  const tickIndexes = [...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])];

  return (
    <TrendFrame title={title} subtitle={subtitle}>
      {maximum === 0 ? (
        <p className="contribution-chart-card__empty">No tasks were created during this date range.</p>
      ) : (
        <svg className="contribution-trend" viewBox={`0 0 ${chartWidth} ${chartHeight}`} role="img" aria-label={`${title}, maximum ${maximum} tasks in one day`}>
          {countAxisTicks(maximum).map((tick) => {
            const y = chartMargin.top + plotHeight - (tick / maximum) * plotHeight;
            return <g key={tick}><line className="contribution-trend__grid" x1={chartMargin.left} x2={chartWidth - chartMargin.right} y1={y} y2={y} /><text className="contribution-trend__axis" x={chartMargin.left - 8} y={y + 4} textAnchor="end">{tick}</text></g>;
          })}
          <line className="contribution-trend__axis-line" x1={chartMargin.left} x2={chartWidth - chartMargin.right} y1={baseline} y2={baseline} />
          {points.map((point, index) => {
            if (point.count === 0) return null;
            const height = (point.count / maximum) * plotHeight;
            const x = chartMargin.left + index * step + (step - barWidth) / 2;
            const taskLabel = point.count === 1 ? "task" : "tasks";
            return <rect key={point.date} className="contribution-trend__bar" x={x} y={baseline - height} width={barWidth} height={height} rx="2"><title>{`${point.date}: ${point.count} ${taskLabel} created`}</title></rect>;
          })}
          {tickIndexes.map((index) => points[index] && <text key={points[index].date} className="contribution-trend__date" x={chartMargin.left + index * step + step / 2} y={chartHeight - 9} textAnchor="middle">{dateLabel(points[index].date)}</text>)}
        </svg>
      )}
      <details className="contribution-chart-data"><summary>View creation data</summary><div className="table-wrap"><table className="contribution-data-table"><caption>Daily task creation</caption><thead><tr><th scope="col">Date</th><th scope="col">Tasks created</th></tr></thead><tbody>{points.map((point) => <tr key={point.date}><th scope="row">{point.date}</th><td>{point.count}</td></tr>)}</tbody></table></div></details>
    </TrendFrame>
  );
}

function CycleChart({ points }: { points: InsightDailyCycle[] }) {
  const values = points.filter((point) => point.average_hours !== null);
  const maximum = Math.max(0, ...values.map((point) => point.average_hours ?? 0));
  const scale = cycleAxisScale(maximum);
  const maximumInUnit = maximum * scale.multiplier;
  const axisMaximum = maximumInUnit || 1;
  const tickIndexes = [...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])];
  const coordinates = values.map((point) => {
    const index = points.indexOf(point);
    const x = chartMargin.left + (points.length > 1 ? (index / (points.length - 1)) * plotWidth : plotWidth / 2);
    const y = chartMargin.top + plotHeight - (((point.average_hours ?? 0) * scale.multiplier) / axisMaximum) * plotHeight;
    return { point, x, y };
  });
  const path = coordinates.map(({ x, y }, index) => `${index === 0 ? "M" : "L"}${x},${y}`).join(" ");

  return (
    <TrendFrame title="Work item cycle time" subtitle={`Creation to completion · ${scale.label}`}>
      {!values.length ? (
        <p className="contribution-chart-card__empty">No currently completed tasks fall within this date range.</p>
      ) : (
        <svg className="contribution-trend" viewBox={`0 0 ${chartWidth} ${chartHeight}`} role="img" aria-label={`Average completion time trend, ${values.length} days with completions, maximum ${formatCycleDuration(maximum)}`}>
          {[0, axisMaximum / 2, axisMaximum].map((tick) => {
            const y = chartMargin.top + plotHeight - (tick / axisMaximum) * plotHeight;
            return <g key={tick}><line className="contribution-trend__grid" x1={chartMargin.left} x2={chartWidth - chartMargin.right} y1={y} y2={y} /><text className="contribution-trend__axis" x={chartMargin.left - 8} y={y + 4} textAnchor="end">{formatCycleNumber(tick)}{scale.suffix}</text></g>;
          })}
          <line className="contribution-trend__axis-line" x1={chartMargin.left} x2={chartWidth - chartMargin.right} y1={chartMargin.top + plotHeight} y2={chartMargin.top + plotHeight} />
          {path && <path className="contribution-trend__line" d={path} />}
          {coordinates.map(({ point, x, y }) => {
            const taskLabel = point.count === 1 ? "completed task" : "completed tasks";
            return <circle key={point.date} className="contribution-trend__point" cx={x} cy={y} r="3.5"><title>{`${point.date}: ${formatCycleDuration(point.average_hours ?? 0)} across ${point.count} ${taskLabel}`}</title></circle>;
          })}
          {tickIndexes.map((index) => points[index] && <text key={points[index].date} className="contribution-trend__date" x={chartMargin.left + (points.length > 1 ? (index / (points.length - 1)) * plotWidth : plotWidth / 2)} y={chartHeight - 9} textAnchor="middle">{dateLabel(points[index].date)}</text>)}
        </svg>
      )}
      <details className="contribution-chart-data"><summary>View completion data</summary><div className="table-wrap"><table className="contribution-data-table"><caption>Daily completion cycle time</caption><thead><tr><th scope="col">Completion date</th><th scope="col">Tasks completed</th><th scope="col">Average cycle time</th></tr></thead><tbody>{points.map((point) => <tr key={point.date}><th scope="row">{point.date}</th><td>{point.count}</td><td>{point.average_hours === null ? "No completions" : formatCycleDuration(point.average_hours)}</td></tr>)}</tbody></table></div></details>
    </TrendFrame>
  );
}
