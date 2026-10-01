\set ON_ERROR_STOP on

-- Run using studycrew_app after migrations and permissions.sql are applied.
-- This reads PostgreSQL catalogues only; it does not change rows, roles or DDL.
-- Let psql prompt for the password; never put credentials in command arguments.
BEGIN READ ONLY;

DO $$
DECLARE
    delete_allowlist constant text[] := ARRAY[
        'public.django_session',
        'public.tasks_taskassignment',
        'public.accounts_pendingemailchange'
    ];
    audit_tables constant text[] := ARRAY[
        'public.activity_activityevent',
        'public.activity_siteauditevent'
    ];
    required_table text;
    capability text;
    relation record;
    checked_tables integer := 0;
    audit_function oid := to_regprocedure('public.prevent_studycrew_audit_mutation()');
BEGIN
    IF current_user <> 'studycrew_app' OR session_user <> 'studycrew_app' THEN
        RAISE EXCEPTION 'Connect directly as studycrew_app, not a migration or administrator role';
    END IF;
    IF current_database() <> 'studycrew' THEN
        RAISE EXCEPTION 'Connect to the studycrew database';
    END IF;

    -- Include membership, not merely directly granted privileges: SET ROLE to a
    -- privileged/owning identity would otherwise bypass the runtime limits.
    IF EXISTS (
        SELECT 1 FROM pg_roles role
        WHERE pg_has_role(current_user, role.oid, 'MEMBER')
          AND (role.rolsuper OR role.rolcreaterole OR role.rolcreatedb
               OR role.rolreplication OR role.rolbypassrls)
    ) THEN
        RAISE EXCEPTION 'Runtime identity has a privileged role or role membership';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_roles role
        WHERE role.rolname <> current_user
          AND pg_has_role(current_user, role.oid, 'MEMBER')
    ) THEN
        RAISE EXCEPTION 'Runtime identity must not assume another role, including built-in server-access roles';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_roles role
        WHERE pg_has_role(current_user, role.oid, 'MEMBER')
          AND (
              role.oid = (SELECT datdba FROM pg_database WHERE datname = current_database())
              OR role.oid IN (
                  SELECT nspowner FROM pg_namespace
                  WHERE nspname !~ '^pg_' AND nspname <> 'information_schema'
              )
              OR role.oid IN (
                  SELECT object.relowner FROM pg_class object
                  JOIN pg_namespace schema ON schema.oid = object.relnamespace
                  WHERE schema.nspname = 'public'
              )
          )
    ) THEN
        RAISE EXCEPTION 'Runtime identity owns, or can assume ownership of, database/schema objects';
    END IF;
    IF NOT has_database_privilege(current_user, current_database(), 'CONNECT')
       OR has_database_privilege(current_user, current_database(), 'CREATE')
       OR has_database_privilege(current_user, current_database(), 'TEMP') THEN
        RAISE EXCEPTION 'Runtime database capabilities are not CONNECT-only';
    END IF;
    IF NOT has_schema_privilege(current_user, 'public', 'USAGE') OR EXISTS (
        SELECT 1 FROM pg_namespace schema
        WHERE schema.nspname !~ '^pg_'
          AND schema.nspname <> 'information_schema'
          AND has_schema_privilege(current_user, schema.oid, 'CREATE')
    ) THEN
        RAISE EXCEPTION 'Runtime identity lacks public USAGE or has schema CREATE rights';
    END IF;

    FOREACH required_table IN ARRAY delete_allowlist || audit_tables LOOP
        IF to_regclass(required_table) IS NULL THEN
            RAISE EXCEPTION 'Required table is missing: %', required_table;
        END IF;
    END LOOP;
    FOR relation IN
        SELECT object.oid, 'public.' || quote_ident(object.relname) AS name
        FROM pg_class object
        JOIN pg_namespace schema ON schema.oid = object.relnamespace
        WHERE schema.nspname = 'public' AND object.relkind IN ('r', 'p')
        ORDER BY object.relname
    LOOP
        checked_tables := checked_tables + 1;
        FOREACH capability IN ARRAY ARRAY['SELECT', 'INSERT'] LOOP
            IF NOT has_table_privilege(current_user, relation.oid, capability) THEN
                RAISE EXCEPTION 'Runtime identity lacks % on %', capability, relation.name;
            END IF;
        END LOOP;
        IF has_table_privilege(current_user, relation.oid, 'DELETE')
           <> (relation.name = ANY(delete_allowlist)) THEN
            RAISE EXCEPTION 'DELETE capability does not match the allowlist: %', relation.name;
        END IF;
        IF has_table_privilege(current_user, relation.oid, 'UPDATE')
           <> (NOT (relation.name = ANY(audit_tables))) THEN
            RAISE EXCEPTION 'UPDATE capability does not preserve append-only audits: %', relation.name;
        END IF;
        FOREACH capability IN ARRAY ARRAY['TRUNCATE', 'REFERENCES', 'TRIGGER'] LOOP
            IF has_table_privilege(current_user, relation.oid, capability) THEN
                RAISE EXCEPTION 'Unexpected % capability on %', capability, relation.name;
            END IF;
        END LOOP;
    END LOOP;

    IF audit_function IS NULL OR has_function_privilege(current_user, audit_function, 'EXECUTE') THEN
        RAISE EXCEPTION 'Audit guard is missing or directly callable by the runtime identity';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_proc function
        WHERE function.oid = audit_function AND function.prosecdef
          AND 'search_path=pg_catalog' = ANY(function.proconfig)
    ) THEN
        RAISE EXCEPTION 'Audit function does not use the reviewed security-definer/search-path guard';
    END IF;
    FOREACH required_table IN ARRAY audit_tables LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger trigger
            WHERE trigger.tgrelid = to_regclass(required_table)
              AND trigger.tgfoid = audit_function AND NOT trigger.tgisinternal
              AND trigger.tgenabled IN ('O', 'A') AND trigger.tgtype = 27
        ) THEN
            RAISE EXCEPTION 'Audit table lacks its enabled BEFORE ROW UPDATE/DELETE guard: %', required_table;
        END IF;
    END LOOP;

    FOR relation IN
        SELECT object.oid, 'public.' || quote_ident(object.relname) AS name
        FROM pg_class object
        JOIN pg_namespace schema ON schema.oid = object.relnamespace
        WHERE schema.nspname = 'public' AND object.relkind = 'S'
    LOOP
        IF NOT has_sequence_privilege(current_user, relation.oid, 'USAGE')
           OR NOT has_sequence_privilege(current_user, relation.oid, 'SELECT')
           OR has_sequence_privilege(current_user, relation.oid, 'UPDATE') THEN
            RAISE EXCEPTION 'Sequence capabilities are not USAGE/SELECT only: %', relation.name;
        END IF;
    END LOOP;
    RAISE NOTICE 'PASS: % public tables checked; DELETE allowlist, no DDL/ownership, append-only audits and sequences verified', checked_tables;
END;
$$;

ROLLBACK;
