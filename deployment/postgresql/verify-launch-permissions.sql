\set ON_ERROR_STOP on
BEGIN READ ONLY;
DO $$
DECLARE
    delete_allowlist constant text[] := ARRAY[
        'public.django_session', 'public.tasks_taskassignment', 'public.accounts_pendingemailchange',
        'public.accounts_accountdevicesession', 'public.accounts_accountsecuritytoken',
        'public.accounts_accountsecuritythrottle', 'public.accounts_recoveryemail', 'public.activity_notification',
        'public.accounts_user_groups', 'public.accounts_user_user_permissions',
        'public.campus_projectcourse', 'public.campus_taskdependency', 'public.campus_resourcelink',
        'public.coordination_weeklyavailability', 'public.operations_useralert', 'public.operations_userblock',
        'public.operations_contactrequest', 'public.operations_ratebucket', 'public.operations_webhookreceipt',
        'public.recruiting_bookmark', 'public.documents_store_projectdocument',
        'public.documents_store_documentversion', 'public.documents_store_documenttag',
        'public.documents_store_uploaddailyusage', 'public.learning_exchange_importpreview',
        'public.project_chat_chatpresence', 'public.offline_sync_tasksyncreceipt'
    ];
    audit_tables constant text[] := ARRAY[
        'public.activity_activityevent', 'public.activity_siteauditevent',
        'public.coordination_coordinationevent', 'public.coordination_claimreview', 'public.operations_operationaudit'
    ];
    relation record;
    required_table text;
    capability text;
    guard oid := to_regprocedure('public.prevent_studycrew_audit_mutation()');
BEGIN
    IF current_user <> 'studycrew_app' OR session_user <> 'studycrew_app' OR current_database() <> 'studycrew' THEN
        RAISE EXCEPTION 'Connect directly to studycrew as its runtime studycrew_app role';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles role WHERE pg_has_role(current_user, role.oid, 'MEMBER')
        AND (role.rolname <> current_user OR role.rolsuper OR role.rolcreatedb OR role.rolcreaterole OR role.rolreplication OR role.rolbypassrls)) THEN
        RAISE EXCEPTION 'Runtime role has a privileged capability or can assume another role';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_class object JOIN pg_namespace schema ON schema.oid = object.relnamespace
        WHERE schema.nspname = 'public' AND pg_has_role(current_user, object.relowner, 'MEMBER')) THEN
        RAISE EXCEPTION 'Runtime role owns application objects';
    END IF;
    IF has_database_privilege(current_user, current_database(), 'CREATE') OR has_database_privilege(current_user, current_database(), 'TEMP') THEN
        RAISE EXCEPTION 'Runtime role can create database objects';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_namespace schema WHERE schema.nspname !~ '^pg_' AND schema.nspname <> 'information_schema'
        AND has_schema_privilege(current_user, schema.oid, 'CREATE')) THEN
        RAISE EXCEPTION 'Runtime role can create schema objects';
    END IF;
    FOREACH required_table IN ARRAY delete_allowlist || audit_tables LOOP
        IF to_regclass(required_table) IS NULL THEN RAISE EXCEPTION 'Missing required table: %', required_table; END IF;
    END LOOP;
    FOR relation IN SELECT object.oid, 'public.' || quote_ident(object.relname) AS name
        FROM pg_class object JOIN pg_namespace schema ON schema.oid = object.relnamespace
        WHERE schema.nspname = 'public' AND object.relkind IN ('r', 'p') LOOP
        IF NOT has_table_privilege(current_user, relation.oid, 'SELECT') OR NOT has_table_privilege(current_user, relation.oid, 'INSERT') THEN
            RAISE EXCEPTION 'Runtime role lacks normal read/create capability: %', relation.name;
        END IF;
        IF has_table_privilege(current_user, relation.oid, 'DELETE') <> (relation.name = ANY(delete_allowlist)) THEN
            RAISE EXCEPTION 'DELETE capability differs from reviewed allowlist: %', relation.name;
        END IF;
        IF has_table_privilege(current_user, relation.oid, 'UPDATE') <> (NOT (relation.name = ANY(audit_tables))) THEN
            RAISE EXCEPTION 'UPDATE capability differs from immutable audit policy: %', relation.name;
        END IF;
        FOREACH capability IN ARRAY ARRAY['TRUNCATE', 'REFERENCES', 'TRIGGER'] LOOP
            IF has_table_privilege(current_user, relation.oid, capability) THEN RAISE EXCEPTION 'Unexpected % on %', capability, relation.name; END IF;
        END LOOP;
    END LOOP;
    IF guard IS NULL OR has_function_privilege(current_user, guard, 'EXECUTE') THEN RAISE EXCEPTION 'Audit function absent or directly callable'; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_proc function WHERE function.oid = guard AND function.prosecdef AND 'search_path=pg_catalog' = ANY(function.proconfig)) THEN
        RAISE EXCEPTION 'Audit function security-definer/search-path is not hardened';
    END IF;
    FOREACH required_table IN ARRAY audit_tables LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_trigger trigger WHERE trigger.tgrelid = to_regclass(required_table)
            AND trigger.tgfoid = guard AND NOT trigger.tgisinternal AND trigger.tgenabled IN ('O', 'A') AND trigger.tgtype = 27) THEN
            RAISE EXCEPTION 'Missing immutable audit guard: %', required_table;
        END IF;
    END LOOP;
    RAISE NOTICE 'PASS: launch application tables, explicit DELETE allowlist and five immutable audit tables checked';
END;
$$;
ROLLBACK;
