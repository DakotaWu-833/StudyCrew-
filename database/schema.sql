-- Assignment 1 StudyCrew physical design model (PostgreSQL 16), retained as a
-- historical design artefact. Do not use this 13-table sketch to initialise the
-- current 18-table Django application; its migrations define the live schema.
-- UUIDs prevent guessable public identifiers; timestamptz stores instants in UTC.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
    user_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email varchar(254) NOT NULL,
    password_hash varchar(255) NOT NULL,
    account_status varchar(16) NOT NULL DEFAULT 'active'
        CHECK (account_status IN ('active', 'disabled')),
    created_at timestamptz NOT NULL DEFAULT now(),
    last_login_at timestamptz,
    CONSTRAINT uq_users_email UNIQUE (email),
    CONSTRAINT ck_users_email_lower CHECK (email = lower(email))
);

-- One-to-one: the primary key is also the foreign key to users.
CREATE TABLE profiles (
    user_id uuid PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    display_name varchar(80) NOT NULL CHECK (char_length(display_name) BETWEEN 2 AND 80),
    course_code varchar(20),
    time_zone varchar(64) NOT NULL DEFAULT 'Australia/Sydney',
    biography varchar(500),
    avatar_url varchar(2048),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE projects (
    project_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name varchar(100) NOT NULL CHECK (char_length(name) BETWEEN 3 AND 100),
    description varchar(2000),
    due_at timestamptz,
    created_by uuid NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz
);

-- Many-to-many: users and projects are joined by project_members.
CREATE TABLE project_members (
    project_id uuid NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    role varchar(16) NOT NULL DEFAULT 'member'
        CHECK (role IN ('owner', 'facilitator', 'member')),
    joined_at timestamptz NOT NULL DEFAULT now(),
    removed_at timestamptz,
    PRIMARY KEY (project_id, user_id)
);

CREATE UNIQUE INDEX uq_project_single_active_owner
    ON project_members(project_id)
    WHERE role = 'owner' AND removed_at IS NULL;

CREATE TABLE project_invitations (
    invitation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    invited_email varchar(254) NOT NULL CHECK (invited_email = lower(invited_email)),
    invited_by uuid NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    status varchar(16) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'accepted', 'declined', 'cancelled', 'expired')),
    token_hash varchar(255) NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    responded_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_pending_project_invitation
    ON project_invitations(project_id, invited_email)
    WHERE status = 'pending';

-- One-to-many: one project owns many tasks.
CREATE TABLE tasks (
    task_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    title varchar(120) NOT NULL CHECK (char_length(title) BETWEEN 3 AND 120),
    description varchar(4000),
    status varchar(16) NOT NULL DEFAULT 'todo'
        CHECK (status IN ('todo', 'in_progress', 'blocked', 'done')),
    priority varchar(16) NOT NULL DEFAULT 'medium'
        CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
    blocker_note varchar(500),
    due_at timestamptz,
    completed_at timestamptz,
    created_by uuid NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz,
    CONSTRAINT ck_task_blocker_note CHECK
        (status <> 'blocked' OR char_length(blocker_note) BETWEEN 3 AND 500),
    CONSTRAINT ck_task_completion CHECK
        ((status = 'done' AND completed_at IS NOT NULL) OR
         (status <> 'done' AND completed_at IS NULL))
);

CREATE TABLE task_assignees (
    task_id uuid NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    assigned_by uuid NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    assigned_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (task_id, user_id)
);

CREATE TABLE task_comments (
    comment_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id uuid NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    author_id uuid NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    body varchar(2000) NOT NULL CHECK (char_length(body) BETWEEN 1 AND 2000),
    created_at timestamptz NOT NULL DEFAULT now(),
    edited_at timestamptz,
    deleted_at timestamptz,
    moderated_by uuid REFERENCES users(user_id) ON DELETE RESTRICT
);

CREATE TABLE meetings (
    meeting_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    title varchar(120) NOT NULL CHECK (char_length(title) BETWEEN 3 AND 120),
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    location_or_url varchar(2048),
    agenda varchar(4000),
    organised_by uuid NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    cancelled_at timestamptz,
    archived_at timestamptz,
    CONSTRAINT ck_meeting_time_order CHECK (ends_at > starts_at),
    CONSTRAINT ck_meeting_archive_terminal CHECK (
        archived_at IS NULL OR cancelled_at IS NOT NULL OR ends_at <= archived_at
    )
);

CREATE TABLE meeting_attendees (
    meeting_id uuid NOT NULL REFERENCES meetings(meeting_id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    response varchar(16) NOT NULL DEFAULT 'pending'
        CHECK (response IN ('pending', 'accepted', 'declined')),
    availability_note varchar(500),
    responded_at timestamptz,
    PRIMARY KEY (meeting_id, user_id)
);

-- Append-only audit evidence. Totals are calculated, never duplicated here.
CREATE TABLE activity_events (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
    actor_id uuid NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    event_type varchar(40) NOT NULL CHECK (event_type IN (
        'member_joined', 'member_role_changed', 'member_removed',
        'task_created', 'task_updated', 'task_status_changed',
        'comment_created', 'comment_edited', 'comment_deleted',
        'meeting_created', 'meeting_updated', 'meeting_cancelled',
        'meeting_archived', 'meeting_rsvp',
        'task_reminder_sent', 'meeting_reminder_sent'
    )),
    task_id uuid REFERENCES tasks(task_id) ON DELETE SET NULL,
    comment_id uuid REFERENCES task_comments(comment_id) ON DELETE SET NULL,
    meeting_id uuid REFERENCES meetings(meeting_id) ON DELETE SET NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_activity_single_target CHECK
        ((task_id IS NOT NULL)::int + (comment_id IS NOT NULL)::int +
         (meeting_id IS NOT NULL)::int <= 1)
);

CREATE TABLE notifications (
    notification_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recipient_id uuid NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    project_id uuid NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    source_event_id bigint NOT NULL REFERENCES activity_events(event_id) ON DELETE CASCADE,
    notification_type varchar(24) NOT NULL CHECK (notification_type IN
        ('invitation', 'task_assignment', 'comment_mention', 'meeting_change')),
    created_at timestamptz NOT NULL DEFAULT now(),
    read_at timestamptz,
    CONSTRAINT uq_notification_source_recipient UNIQUE (recipient_id, source_event_id)
);

CREATE TABLE export_jobs (
    export_job_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    requested_by uuid NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    format varchar(8) NOT NULL CHECK (format IN ('pdf', 'csv')),
    range_start date NOT NULL,
    range_end date NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'processing', 'ready', 'failed', 'expired')),
    storage_key varchar(512),
    error_message varchar(500),
    requested_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    expires_at timestamptz,
    CONSTRAINT ck_export_range CHECK
        (range_end >= range_start AND range_end - range_start <= 366),
    CONSTRAINT ck_export_ready_file CHECK
        (status <> 'ready' OR (storage_key IS NOT NULL AND expires_at IS NOT NULL))
);

CREATE INDEX ix_members_user_active ON project_members(user_id) WHERE removed_at IS NULL;
CREATE INDEX ix_tasks_project_board ON tasks(project_id, status, priority) WHERE archived_at IS NULL;
CREATE INDEX ix_tasks_due_at ON tasks(project_id, due_at) WHERE archived_at IS NULL;
CREATE INDEX ix_comments_task_time ON task_comments(task_id, created_at);
CREATE INDEX ix_meetings_project_start ON meetings(project_id, starts_at);
CREATE INDEX ix_meetings_project_archive
    ON meetings(project_id, archived_at, starts_at);
CREATE INDEX ix_activity_project_time ON activity_events(project_id, occurred_at);
CREATE INDEX ix_activity_actor_time ON activity_events(actor_id, occurred_at);
CREATE INDEX ix_notifications_unread ON notifications(recipient_id, created_at DESC) WHERE read_at IS NULL;

