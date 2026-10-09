\set ON_ERROR_STOP on

-- Apply deploy/postgresql/permissions.sql first, after every migration.
-- The database and role names follow the existing reviewed deployment example.
BEGIN;

REVOKE DELETE ON ALL TABLES IN SCHEMA public FROM studycrew_app;
GRANT DELETE ON TABLE
    public.django_session,
    public.tasks_taskassignment,
    public.accounts_pendingemailchange,
    public.accounts_accountdevicesession,
    public.accounts_accountsecuritytoken,
    public.accounts_accountsecuritythrottle,
    public.accounts_recoveryemail,
    public.accounts_user_groups,
    public.accounts_user_user_permissions,
    public.activity_notification,
    public.campus_projectcourse,
    public.campus_taskdependency,
    public.campus_resourcelink,
    public.coordination_weeklyavailability,
    public.operations_useralert,
    public.operations_userblock,
    public.operations_contactrequest,
    public.operations_ratebucket,
    public.operations_webhookreceipt,
    public.recruiting_bookmark,
    public.documents_store_projectdocument,
    public.documents_store_documentversion,
    public.documents_store_documenttag,
    public.documents_store_uploaddailyusage,
    public.learning_exchange_importpreview,
    public.project_chat_chatpresence,
    public.offline_sync_tasksyncreceipt
TO studycrew_app;

-- Domain history remains retained. The runtime role cannot hard-delete users,
-- projects, tasks, meetings, contribution claims or any audit rows.
DROP TRIGGER IF EXISTS coordination_event_append_only ON public.coordination_coordinationevent;
CREATE TRIGGER coordination_event_append_only
BEFORE UPDATE OR DELETE ON public.coordination_coordinationevent
FOR EACH ROW EXECUTE FUNCTION public.prevent_studycrew_audit_mutation();

DROP TRIGGER IF EXISTS claim_review_append_only ON public.coordination_claimreview;
CREATE TRIGGER claim_review_append_only
BEFORE UPDATE OR DELETE ON public.coordination_claimreview
FOR EACH ROW EXECUTE FUNCTION public.prevent_studycrew_audit_mutation();

DROP TRIGGER IF EXISTS operation_audit_append_only ON public.operations_operationaudit;
CREATE TRIGGER operation_audit_append_only
BEFORE UPDATE OR DELETE ON public.operations_operationaudit
FOR EACH ROW EXECUTE FUNCTION public.prevent_studycrew_audit_mutation();

REVOKE UPDATE, DELETE ON public.coordination_coordinationevent FROM studycrew_app;
REVOKE UPDATE, DELETE ON public.coordination_claimreview FROM studycrew_app;
REVOKE UPDATE, DELETE ON public.operations_operationaudit FROM studycrew_app;
REVOKE UPDATE, DELETE ON public.activity_activityevent FROM studycrew_app;
REVOKE UPDATE, DELETE ON public.activity_siteauditevent FROM studycrew_app;

COMMIT;
