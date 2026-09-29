export type UUID = string;

export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface UserSummary { id: UUID; display_name: string; }

export interface Profile {
  email: string;
  display_name: string;
  course_code: string;
  time_zone: string;
  biography: string;
  avatar_url: string;
  updated_at: string;
}

export interface Me {
  user: UserSummary;
  email: string;
  profile: Profile;
  permissions: { site_moderator: boolean };
}

export type MemberRole = "owner" | "facilitator" | "member";
export interface Project {
  id: UUID;
  name: string;
  description: string;
  due_at: string | null;
  created_by: UserSummary;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  current_user_role: MemberRole;
  member_count: number;
}

export interface Membership {
  id: UUID;
  project: UUID;
  user: UserSummary;
  role: MemberRole;
  joined_at: string;
  removed_at: string | null;
}

export interface Invitation {
  id: UUID;
  project: UUID;
  project_name: string;
  invited_email: string;
  invited_by: UserSummary;
  status: "pending" | "accepted" | "declined" | "cancelled" | "expired";
  expires_at: string;
  responded_at: string | null;
  created_at: string;
  share_token?: string;
}

export type TaskStatus = "todo" | "in_progress" | "blocked" | "done";
export type TaskPriority = "low" | "medium" | "high" | "urgent";
export interface Task {
  id: UUID;
  project: UUID;
  title: string;
  description: string;
  status: TaskStatus;
  priority: TaskPriority;
  blocker_note: string;
  due_at: string | null;
  completed_at: string | null;
  created_by: UserSummary;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  assignees: UserSummary[];
  comment_count: number;
}

export interface Comment {
  id: UUID;
  task: UUID;
  author: UserSummary;
  body: string;
  created_at: string;
  edited_at: string | null;
  deleted_at: string | null;
  is_deleted: boolean;
}

export type RSVP = "pending" | "accepted" | "declined";
export interface Meeting {
  id: UUID;
  project: UUID;
  organiser: UserSummary;
  title: string;
  starts_at: string;
  ends_at: string;
  location: string;
  agenda: string;
  cancelled_at: string | null;
  archived_at: string | null;
  lifecycle_state: "scheduled" | "ended" | "cancelled" | "archived";
  created_at: string;
  updated_at: string;
  attendance_counts: Record<RSVP, number>;
  my_response: RSVP;
  my_availability_note: string;
}

export interface ReminderDelivery {
  recipient_count: number;
  sent_at: string;
}

export interface HolidayAdvisory {
  meeting_date: string;
  available: boolean;
  is_public_holiday: boolean | null;
  holiday_name: string | null;
  source: "live" | "cache" | "stale" | "unavailable";
  message: string;
}

export interface ActivityEvent {
  id: UUID;
  project: UUID;
  actor: UserSummary;
  event_type: string;
  target_type: string;
  target_id: UUID | null;
  metadata: Record<string, unknown>;
  occurred_at: string;
}

export interface MemberInsight {
  user_id: UUID;
  display_name: string;
  role: MemberRole;
  total_events: number;
  completed_tasks: number;
  comments: number;
  accepted_meetings: number;
}

export interface Insights {
  range_start: string;
  range_end: string;
  event_type: string;
  members: MemberInsight[];
  events: ActivityEvent[];
  events_truncated: boolean;
}

export interface Notification {
  id: UUID;
  project: UUID;
  project_name: string;
  notification_type: "invitation" | "task_assignment" | "comment_mention" | "meeting_change";
  target_url: string;
  created_at: string;
  read_at: string | null;
  is_read: boolean;
}

export interface ExportJob {
  id: UUID;
  project: UUID;
  format: "csv" | "pdf";
  range_start: string;
  range_end: string;
  status: "queued" | "processing" | "ready" | "failed" | "expired";
  error_message: string;
  created_at: string;
  completed_at: string | null;
  expires_at: string | null;
  download_url: string | null;
}
