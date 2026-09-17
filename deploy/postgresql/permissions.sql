\set ON_ERROR_STOP on

BEGIN;

REVOKE CONNECT, CREATE, TEMPORARY ON DATABASE studycrew FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM studycrew_app;
GRANT CONNECT ON DATABASE studycrew TO studycrew_app;
GRANT USAGE ON SCHEMA public TO studycrew_app;

-- The web identity can read and mutate rows but receives hard-delete rights
-- only where the running application genuinely needs them.
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO studycrew_app;
REVOKE DELETE ON ALL TABLES IN SCHEMA public FROM studycrew_app;
GRANT DELETE ON TABLE public.django_session TO studycrew_app;
GRANT DELETE ON TABLE public.tasks_taskassignment TO studycrew_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO studycrew_app;
ALTER DEFAULT PRIVILEGES FOR ROLE studycrew_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE ON TABLES TO studycrew_app;
ALTER DEFAULT PRIVILEGES FOR ROLE studycrew_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO studycrew_app;

CREATE OR REPLACE FUNCTION public.prevent_studycrew_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION 'StudyCrew audit records are append-only';
END;
$$;

REVOKE ALL ON FUNCTION public.prevent_studycrew_audit_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.prevent_studycrew_audit_mutation() FROM studycrew_app;

DROP TRIGGER IF EXISTS activity_event_append_only ON public.activity_activityevent;
CREATE TRIGGER activity_event_append_only
BEFORE UPDATE OR DELETE ON public.activity_activityevent
FOR EACH ROW EXECUTE FUNCTION public.prevent_studycrew_audit_mutation();

DROP TRIGGER IF EXISTS site_audit_event_append_only ON public.activity_siteauditevent;
CREATE TRIGGER site_audit_event_append_only
BEFORE UPDATE OR DELETE ON public.activity_siteauditevent
FOR EACH ROW EXECUTE FUNCTION public.prevent_studycrew_audit_mutation();

REVOKE UPDATE, DELETE ON public.activity_activityevent FROM studycrew_app;
REVOKE UPDATE, DELETE ON public.activity_siteauditevent FROM studycrew_app;

COMMIT;
