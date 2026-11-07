CREATE SCHEMA IF NOT EXISTS subsea;
REVOKE ALL ON SCHEMA subsea FROM PUBLIC, subsea_checkpoint;
GRANT USAGE ON SCHEMA subsea TO subsea_app, subsea_tools_ro;
CREATE SCHEMA IF NOT EXISTS subsea_checkpoint AUTHORIZATION subsea_checkpoint;
ALTER SCHEMA subsea_checkpoint OWNER TO subsea_checkpoint;
REVOKE ALL ON SCHEMA subsea_checkpoint FROM PUBLIC, subsea_app, subsea_tools_ro;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

CREATE TABLE IF NOT EXISTS subsea.replays (
    tenant_id text NOT NULL, site_id text NOT NULL, id text NOT NULL,
    payload jsonb NOT NULL, version integer NOT NULL CHECK (version > 0),
    PRIMARY KEY (tenant_id, site_id, id)
);
CREATE TABLE IF NOT EXISTS subsea.observations (
    tenant_id text NOT NULL, site_id text NOT NULL, generation_id text NOT NULL,
    identity text NOT NULL, raw_hash text NOT NULL, payload_hash text NOT NULL,
    observed_at timestamptz NOT NULL, payload jsonb NOT NULL,
    ordinal bigint GENERATED ALWAYS AS IDENTITY,
    PRIMARY KEY (tenant_id, site_id, generation_id, identity, raw_hash, payload_hash),
    FOREIGN KEY (tenant_id, site_id, generation_id)
        REFERENCES subsea.replays (tenant_id, site_id, id)
);
CREATE INDEX IF NOT EXISTS observation_range ON subsea.observations
    (tenant_id, site_id, generation_id, observed_at);
CREATE TABLE IF NOT EXISTS subsea.windows (
    tenant_id text NOT NULL, site_id text NOT NULL, id text NOT NULL,
    generation_id text NOT NULL, end_seconds integer NOT NULL, revision integer NOT NULL,
    predecessor_id text, payload jsonb NOT NULL,
    PRIMARY KEY (tenant_id, site_id, id),
    UNIQUE (tenant_id, site_id, generation_id, end_seconds, revision),
    FOREIGN KEY (tenant_id, site_id, generation_id)
        REFERENCES subsea.replays (tenant_id, site_id, id),
    FOREIGN KEY (tenant_id, site_id, predecessor_id)
        REFERENCES subsea.windows (tenant_id, site_id, id)
);
CREATE TABLE IF NOT EXISTS subsea.episodes (
    tenant_id text NOT NULL, site_id text NOT NULL, id text NOT NULL,
    generation_id text NOT NULL, payload jsonb NOT NULL,
    PRIMARY KEY (tenant_id, site_id, id),
    FOREIGN KEY (tenant_id, site_id, generation_id)
        REFERENCES subsea.replays (tenant_id, site_id, id)
);
CREATE TABLE IF NOT EXISTS subsea.tasks (
    tenant_id text NOT NULL, site_id text NOT NULL, id text NOT NULL,
    generation_id text NOT NULL, root_id text NOT NULL, parent_id text,
    snapshot_id text NOT NULL, episode_id text, role text NOT NULL,
    state text NOT NULL, version integer NOT NULL,
    lease_token text, lease_expires_at timestamptz, deadline timestamptz NOT NULL,
    model_calls integer NOT NULL DEFAULT 0, tool_calls integer NOT NULL DEFAULT 0,
    automatic boolean NOT NULL DEFAULT false, operator_id text NOT NULL DEFAULT 'local',
    idempotency_key text, step_index integer, plan_revision integer,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    initial_payload jsonb NOT NULL, payload jsonb NOT NULL,
    PRIMARY KEY (tenant_id, site_id, id),
    UNIQUE (tenant_id, site_id, generation_id, idempotency_key),
    UNIQUE (tenant_id, site_id, parent_id, plan_revision, step_index),
    FOREIGN KEY (tenant_id, site_id, generation_id)
        REFERENCES subsea.replays (tenant_id, site_id, id),
    FOREIGN KEY (tenant_id, site_id, snapshot_id)
        REFERENCES subsea.windows (tenant_id, site_id, id),
    FOREIGN KEY (tenant_id, site_id, episode_id)
        REFERENCES subsea.episodes (tenant_id, site_id, id),
    FOREIGN KEY (tenant_id, site_id, root_id)
        REFERENCES subsea.tasks (tenant_id, site_id, id),
    FOREIGN KEY (tenant_id, site_id, parent_id)
        REFERENCES subsea.tasks (tenant_id, site_id, id),
    CHECK (model_calls >= 0 AND tool_calls >= 0),
    CHECK (role IN ('sensor_quality','event_diagnosis','operator_response')),
    CHECK (state IN ('QUEUED','RUNNING','WAITING_ON_CHILD',
                    'SUCCEEDED','ABSTAINED','FAILED','CANCELLED'))
);
CREATE TABLE IF NOT EXISTS subsea.events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id text NOT NULL, site_id text NOT NULL, generation_id text NOT NULL,
    type text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    simulated_seconds double precision, snapshot_id text, task_id text,
    payload jsonb NOT NULL,
    FOREIGN KEY (tenant_id, site_id, generation_id)
        REFERENCES subsea.replays (tenant_id, site_id, id),
    FOREIGN KEY (tenant_id, site_id, snapshot_id)
        REFERENCES subsea.windows (tenant_id, site_id, id),
    FOREIGN KEY (tenant_id, site_id, task_id)
        REFERENCES subsea.tasks (tenant_id, site_id, id)
);
CREATE INDEX IF NOT EXISTS event_cursor ON subsea.events
    (tenant_id, site_id, generation_id, id);
CREATE TABLE IF NOT EXISTS subsea.monitor_leases (
    tenant_id text NOT NULL, site_id text NOT NULL, generation_id text NOT NULL,
    owner text NOT NULL, expires_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, site_id, generation_id),
    FOREIGN KEY (tenant_id, site_id, generation_id)
        REFERENCES subsea.replays (tenant_id, site_id, id)
);
CREATE TABLE IF NOT EXISTS subsea.tool_receipts (
    tenant_id text NOT NULL, site_id text NOT NULL, task_id text NOT NULL,
    call_id text NOT NULL, lease_token text NOT NULL, payload jsonb NOT NULL,
    PRIMARY KEY (tenant_id, site_id, task_id, call_id),
    FOREIGN KEY (tenant_id, site_id, task_id)
        REFERENCES subsea.tasks (tenant_id, site_id, id)
);
CREATE TABLE IF NOT EXISTS subsea.attempts (
    tenant_id text NOT NULL, site_id text NOT NULL, task_id text NOT NULL,
    id text NOT NULL, owner text NOT NULL, lease_token text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, site_id, id),
    UNIQUE (tenant_id, site_id, task_id, lease_token),
    FOREIGN KEY (tenant_id, site_id, task_id)
        REFERENCES subsea.tasks (tenant_id, site_id, id)
);
CREATE TABLE IF NOT EXISTS subsea.model_receipts (
    tenant_id text NOT NULL, site_id text NOT NULL, task_id text NOT NULL,
    call_id text NOT NULL, lease_token text NOT NULL, payload jsonb NOT NULL,
    PRIMARY KEY (tenant_id, site_id, task_id, call_id),
    FOREIGN KEY (tenant_id, site_id, task_id)
        REFERENCES subsea.tasks (tenant_id, site_id, id)
);
CREATE TABLE IF NOT EXISTS subsea.control_requests (
    tenant_id text NOT NULL, site_id text NOT NULL, generation_id text NOT NULL,
    idempotency_key text NOT NULL, action_hash text NOT NULL, payload jsonb NOT NULL,
    PRIMARY KEY (tenant_id,site_id,generation_id,idempotency_key),
    FOREIGN KEY (tenant_id,site_id,generation_id)
        REFERENCES subsea.replays (tenant_id,site_id,id)
);
CREATE TABLE IF NOT EXISTS subsea.reuse_bindings (
    tenant_id text NOT NULL, site_id text NOT NULL, parent_id text NOT NULL,
    task_id text NOT NULL,
    PRIMARY KEY (tenant_id,site_id,parent_id,task_id),
    FOREIGN KEY (tenant_id,site_id,parent_id)
        REFERENCES subsea.tasks (tenant_id,site_id,id),
    FOREIGN KEY (tenant_id,site_id,task_id)
        REFERENCES subsea.tasks (tenant_id,site_id,id)
);
-- This singleton contains only provider availability, never tenant/task contents.
CREATE TABLE IF NOT EXISTS subsea.provider_state (
    id text PRIMARY KEY CHECK (id='copilot'),
    failure_code text CHECK (failure_code IN ('proxy_auth','proxy_quota')),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
ALTER TABLE subsea.provider_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE subsea.provider_state FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS provider_status ON subsea.provider_state;
CREATE POLICY provider_status ON subsea.provider_state USING (true) WITH CHECK (true);
REVOKE ALL ON subsea.provider_state FROM PUBLIC, subsea_app,
    subsea_tools_ro, subsea_checkpoint;
INSERT INTO subsea.provider_state (id) VALUES ('copilot') ON CONFLICT DO NOTHING;

CREATE OR REPLACE FUNCTION subsea.get_provider_failure() RETURNS text
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, subsea AS $$
    SELECT failure_code FROM subsea.provider_state WHERE id='copilot';
$$;
CREATE OR REPLACE FUNCTION subsea.mark_provider_failure(
    task_id text, lease_token text, failure_code text
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, subsea AS $$
BEGIN
    IF failure_code NOT IN ('proxy_auth','proxy_quota') OR failure_code IS NULL
    THEN RAISE EXCEPTION 'invalid_provider_failure'; END IF;
    IF NOT EXISTS (SELECT 1 FROM subsea.tasks t
        WHERE t.tenant_id=nullif(current_setting('subsea.tenant_id',true),'')
        AND t.site_id=nullif(current_setting('subsea.site_id',true),'')
        AND t.id=mark_provider_failure.task_id
        AND t.lease_token=mark_provider_failure.lease_token AND t.state='RUNNING'
        AND t.lease_expires_at > clock_timestamp() AND t.deadline > clock_timestamp())
    THEN RAISE EXCEPTION 'stale_lease'; END IF;
    UPDATE subsea.provider_state SET failure_code=mark_provider_failure.failure_code,
        updated_at=clock_timestamp() WHERE id='copilot';
END $$;
CREATE OR REPLACE FUNCTION subsea.clear_provider_failure() RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, subsea AS $$
    UPDATE subsea.provider_state SET failure_code=NULL,updated_at=clock_timestamp()
        WHERE id='copilot';
$$;

CREATE OR REPLACE FUNCTION subsea.immutable_row() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, subsea AS $$
BEGIN
    RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'immutable_evidence';
END $$;

CREATE OR REPLACE FUNCTION subsea.guard_task() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, subsea AS $$
DECLARE
    root_row subsea.tasks; parent_row subsea.tasks;
    total integer; limit_model integer; limit_tool integer;
BEGIN
    -- One generation lock serializes admission and budget reservations across processes.
    PERFORM 1 FROM subsea.replays
      WHERE tenant_id=NEW.tenant_id AND site_id=NEW.site_id AND id=NEW.generation_id
      FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'scope_error'; END IF;
    IF NOT EXISTS (SELECT 1 FROM subsea.windows WHERE tenant_id=NEW.tenant_id
        AND site_id=NEW.site_id AND id=NEW.snapshot_id AND generation_id=NEW.generation_id)
    THEN RAISE EXCEPTION 'scope_error'; END IF;
    IF NEW.episode_id IS NOT NULL AND NOT EXISTS
       (SELECT 1 FROM subsea.episodes WHERE tenant_id=NEW.tenant_id
        AND site_id=NEW.site_id AND id=NEW.episode_id AND generation_id=NEW.generation_id)
    THEN RAISE EXCEPTION 'scope_error'; END IF;
    limit_model := CASE
        WHEN NEW.role='operator_response' AND NEW.payload->>'response_protocol'='engineer-v2'
            THEN 18
        WHEN NEW.role='event_diagnosis' THEN 12
        ELSE 9 END;
    limit_tool := CASE NEW.role WHEN 'event_diagnosis' THEN 24 ELSE 15 END;
    IF TG_OP='INSERT' THEN
        IF NEW.state <> 'QUEUED' OR NEW.model_calls <> 0 OR NEW.tool_calls <> 0
           OR NEW.lease_token IS NOT NULL THEN RAISE EXCEPTION 'invalid_task'; END IF;
        IF NEW.parent_id IS NULL THEN
            PERFORM pg_advisory_xact_lock(hashtextextended(
                NEW.tenant_id || ':' || NEW.site_id || ':admission',0));
            IF NEW.root_id <> NEW.id OR NEW.role <> 'operator_response'
               OR NEW.deadline > clock_timestamp() + interval '900 seconds'
               OR NEW.deadline <= clock_timestamp()
            THEN RAISE EXCEPTION 'invalid_task'; END IF;
            IF NEW.payload->>'purpose'='evaluate_single_agent_baseline'
                AND (current_setting('subsea.qualification',true) IS DISTINCT FROM 'true'
                     OR NEW.automatic)
            THEN RAISE EXCEPTION 'invalid_task'; END IF;
            SELECT count(*) INTO total FROM subsea.tasks WHERE tenant_id=NEW.tenant_id
              AND site_id=NEW.site_id
              AND parent_id IS NULL AND state='QUEUED';
            IF total >= 48 THEN RAISE EXCEPTION 'queue_full'; END IF;
            SELECT coalesce(sum(model_calls),0) INTO total FROM subsea.tasks
                WHERE tenant_id=NEW.tenant_id AND site_id=NEW.site_id
                AND generation_id=NEW.generation_id;
            IF total >= 300 THEN RAISE EXCEPTION 'budget_blocked'; END IF;
            IF NEW.automatic THEN
                IF NEW.episode_id IS NULL THEN RAISE EXCEPTION 'invalid_task'; END IF;
                SELECT count(*) INTO total FROM subsea.tasks WHERE tenant_id=NEW.tenant_id
                  AND site_id=NEW.site_id AND generation_id=NEW.generation_id
                  AND parent_id IS NULL AND automatic;
                IF total >= 18 THEN RAISE EXCEPTION 'budget_blocked'; END IF;
                SELECT count(*) INTO total FROM subsea.tasks WHERE tenant_id=NEW.tenant_id
                  AND site_id=NEW.site_id AND episode_id=NEW.episode_id
                  AND parent_id IS NULL AND automatic;
                IF total >= 9 THEN RAISE EXCEPTION 'budget_blocked'; END IF;
                IF EXISTS (SELECT 1 FROM subsea.tasks WHERE tenant_id=NEW.tenant_id
                  AND site_id=NEW.site_id AND generation_id=NEW.generation_id
                  AND parent_id IS NULL AND automatic
                  AND created_at > clock_timestamp()-interval '20 seconds')
                THEN RAISE EXCEPTION 'budget_blocked'; END IF;
            ELSE
                IF current_setting('subsea.qualification',true) = 'true' THEN
                    IF NEW.payload->>'purpose'='evaluate_single_agent_baseline' THEN
                        SELECT count(*) INTO total FROM subsea.tasks WHERE tenant_id=NEW.tenant_id
                          AND site_id=NEW.site_id AND generation_id=NEW.generation_id
                          AND parent_id IS NULL AND NOT automatic
                          AND payload->>'purpose'='evaluate_single_agent_baseline';
                        IF total >= 3 THEN RAISE EXCEPTION 'budget_blocked'; END IF;
                    ELSE
                        SELECT count(*) INTO total FROM subsea.tasks WHERE tenant_id=NEW.tenant_id
                          AND site_id=NEW.site_id AND generation_id=NEW.generation_id
                          AND parent_id IS NULL AND NOT automatic
                          AND payload->>'purpose' IS DISTINCT FROM 'evaluate_single_agent_baseline';
                        IF total >= 27 THEN RAISE EXCEPTION 'budget_blocked'; END IF;
                    END IF;
                ELSE
                    SELECT count(*) INTO total FROM subsea.tasks WHERE tenant_id=NEW.tenant_id
                      AND site_id=NEW.site_id AND parent_id IS NULL AND NOT automatic
                      AND operator_id=NEW.operator_id
                      AND created_at > clock_timestamp()-interval '60 seconds';
                    IF total >= 9 THEN RAISE EXCEPTION 'budget_blocked'; END IF;
                END IF;
            END IF;
            IF NEW.episode_id IS NOT NULL AND EXISTS (
                SELECT 1 FROM subsea.tasks WHERE tenant_id=NEW.tenant_id
                  AND site_id=NEW.site_id AND episode_id=NEW.episode_id
                  AND parent_id IS NULL AND state IN ('QUEUED','RUNNING','WAITING_ON_CHILD'))
            THEN RAISE EXCEPTION 'episode_busy'; END IF;
        ELSE
            SELECT * INTO parent_row FROM subsea.tasks WHERE tenant_id=NEW.tenant_id
                AND site_id=NEW.site_id AND id=NEW.parent_id FOR UPDATE;
            SELECT * INTO root_row FROM subsea.tasks WHERE tenant_id=NEW.tenant_id
                AND site_id=NEW.site_id AND id=NEW.root_id;
            IF parent_row.id IS NULL OR root_row.id IS NULL
                OR parent_row.root_id <> NEW.root_id
                OR parent_row.snapshot_id <> NEW.snapshot_id
                OR parent_row.generation_id <> NEW.generation_id
                OR parent_row.episode_id IS DISTINCT FROM NEW.episode_id
                OR parent_row.role = 'sensor_quality'
                OR root_row.payload->>'purpose'='evaluate_single_agent_baseline'
                OR NEW.role = 'operator_response'
                OR (parent_row.role = 'event_diagnosis' AND NEW.role <> 'sensor_quality')
                OR NEW.deadline <> root_row.deadline
                OR NEW.step_index IS NULL OR NEW.step_index < 0
                OR NEW.plan_revision IS NULL OR NEW.plan_revision < 1
            THEN RAISE EXCEPTION 'scope_error'; END IF;
            IF parent_row.state NOT IN ('RUNNING','WAITING_ON_CHILD')
                OR parent_row.lease_token IS DISTINCT FROM
                   nullif(current_setting('subsea.lease_token',true),'')
                OR parent_row.lease_expires_at <= clock_timestamp()
            THEN RAISE EXCEPTION 'stale_lease'; END IF;
            SELECT count(*) INTO total FROM subsea.tasks WHERE tenant_id=NEW.tenant_id
                AND site_id=NEW.site_id AND root_id=NEW.root_id AND parent_id IS NOT NULL;
            IF total >= 2 THEN RAISE EXCEPTION 'budget_blocked'; END IF;
        END IF;
    ELSE
        IF NEW.payload->>'response_protocol' IS DISTINCT FROM OLD.payload->>'response_protocol'
        THEN RAISE EXCEPTION 'scope_error'; END IF;
        IF (NEW.generation_id,NEW.root_id,NEW.parent_id,NEW.snapshot_id,NEW.episode_id,NEW.role,
            NEW.deadline,NEW.automatic,NEW.operator_id,NEW.idempotency_key)
           IS DISTINCT FROM
           (OLD.generation_id,OLD.root_id,OLD.parent_id,OLD.snapshot_id,OLD.episode_id,OLD.role,
            OLD.deadline,OLD.automatic,OLD.operator_id,OLD.idempotency_key)
        THEN RAISE EXCEPTION 'scope_error'; END IF;
        IF NEW.version <> OLD.version+1 THEN RAISE EXCEPTION 'version_conflict'; END IF;
        IF OLD.state IN ('SUCCEEDED','ABSTAINED','FAILED','CANCELLED')
        THEN RAISE EXCEPTION 'terminal_task'; END IF;
        IF current_setting('subsea.action',true) = 'claim' THEN
            IF NOT (OLD.state='QUEUED' OR
                (OLD.state='RUNNING' AND OLD.lease_expires_at <= clock_timestamp()) OR
                NEW.state='FAILED' AND OLD.deadline <= clock_timestamp())
            THEN RAISE EXCEPTION 'stale_lease'; END IF;
        ELSIF current_setting('subsea.action',true) = 'resume' THEN
            IF OLD.state <> 'WAITING_ON_CHILD' OR NEW.state <> 'QUEUED'
            THEN RAISE EXCEPTION 'invalid_transition'; END IF;
        ELSE
            IF OLD.state IN ('RUNNING','WAITING_ON_CHILD') AND
                (OLD.lease_token IS DISTINCT FROM
                    nullif(current_setting('subsea.lease_token',true),'')
                 OR OLD.lease_expires_at <= clock_timestamp()
                 OR OLD.deadline <= clock_timestamp())
            THEN RAISE EXCEPTION 'stale_lease'; END IF;
            IF NEW.state <> OLD.state AND NOT (
                (OLD.state='RUNNING' AND NEW.state IN
                  ('WAITING_ON_CHILD','SUCCEEDED','ABSTAINED','FAILED','CANCELLED'))
                OR (OLD.state='QUEUED' AND NEW.state='CANCELLED'))
            THEN RAISE EXCEPTION 'invalid_transition'; END IF;
            IF NEW.lease_token IS DISTINCT FROM OLD.lease_token OR
               NEW.lease_expires_at IS DISTINCT FROM OLD.lease_expires_at
            THEN RAISE EXCEPTION 'stale_lease'; END IF;
        END IF;
        IF NEW.model_calls < OLD.model_calls OR NEW.tool_calls < OLD.tool_calls
           OR NEW.model_calls > OLD.model_calls+1 OR NEW.tool_calls > OLD.tool_calls+1
        THEN RAISE EXCEPTION 'budget_blocked'; END IF;
    END IF;
    IF NEW.model_calls > limit_model OR NEW.tool_calls > limit_tool
    THEN RAISE EXCEPTION 'budget_blocked'; END IF;
    SELECT coalesce(sum(model_calls),0) INTO total FROM subsea.tasks
      WHERE tenant_id=NEW.tenant_id AND site_id=NEW.site_id
      AND generation_id=NEW.generation_id AND id<>NEW.id;
    IF total+NEW.model_calls > 300 THEN RAISE EXCEPTION 'budget_blocked'; END IF;
    SELECT coalesce(sum(model_calls),0) INTO total FROM subsea.tasks
      WHERE tenant_id=NEW.tenant_id AND site_id=NEW.site_id AND root_id=NEW.root_id AND id<>NEW.id;
    IF total+NEW.model_calls > 30 THEN RAISE EXCEPTION 'budget_blocked'; END IF;
    SELECT coalesce(sum(tool_calls),0) INTO total FROM subsea.tasks
      WHERE tenant_id=NEW.tenant_id AND site_id=NEW.site_id AND root_id=NEW.root_id AND id<>NEW.id;
    IF total+NEW.tool_calls > 54 THEN RAISE EXCEPTION 'budget_blocked'; END IF;
    IF NOT coalesce(
        NEW.payload->>'tenant_id'=NEW.tenant_id AND NEW.payload->>'site_id'=NEW.site_id
        AND NEW.payload->>'id'=NEW.id AND NEW.payload->>'generation_id'=NEW.generation_id
        AND NEW.payload->>'root_id'=NEW.root_id
        AND (NEW.payload->>'parent_id') IS NOT DISTINCT FROM NEW.parent_id
        AND NEW.payload->>'snapshot_id'=NEW.snapshot_id
        AND (NEW.payload->>'episode_id') IS NOT DISTINCT FROM NEW.episode_id
        AND NEW.payload->>'role'=NEW.role AND NEW.payload->>'state'=NEW.state
        AND (NEW.payload->>'version')::integer=NEW.version
        AND (NEW.payload->>'model_calls')::integer=NEW.model_calls
        AND (NEW.payload->>'tool_calls')::integer=NEW.tool_calls
        AND (NEW.payload->>'automatic')::boolean=NEW.automatic
        AND (NEW.payload->>'deadline')::timestamptz=NEW.deadline
        AND (NEW.payload->>'lease_token') IS NOT DISTINCT FROM NEW.lease_token
        AND (NEW.payload->>'lease_expires_at')::timestamptz
            IS NOT DISTINCT FROM NEW.lease_expires_at, false)
    THEN RAISE EXCEPTION 'task_identity_conflict'; END IF;
    RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION subsea.guard_reuse() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, subsea AS $$
DECLARE parent_row subsea.tasks; source_row subsea.tasks; quality_row subsea.tasks;
BEGIN
    SELECT * INTO parent_row FROM subsea.tasks WHERE tenant_id=NEW.tenant_id
        AND site_id=NEW.site_id AND id=NEW.parent_id FOR UPDATE;
    SELECT * INTO source_row FROM subsea.tasks WHERE tenant_id=NEW.tenant_id
        AND site_id=NEW.site_id AND id=NEW.task_id;
    IF parent_row.id IS NULL OR source_row.id IS NULL
        OR parent_row.role <> 'operator_response'
        OR parent_row.payload->'plan' <> '["reuse","answer"]'::jsonb
        OR parent_row.state <> 'RUNNING'
        OR parent_row.lease_token IS DISTINCT FROM
            nullif(current_setting('subsea.lease_token',true),'')
        OR parent_row.lease_expires_at <= clock_timestamp()
        OR parent_row.deadline <= clock_timestamp()
    THEN RAISE EXCEPTION 'stale_lease'; END IF;
    IF (source_row.generation_id,source_row.snapshot_id,source_row.payload->>'mode')
        IS DISTINCT FROM
        (parent_row.generation_id,parent_row.snapshot_id,parent_row.payload->>'mode')
        OR source_row.parent_id IS DISTINCT FROM source_row.root_id
        OR source_row.role NOT IN ('sensor_quality','event_diagnosis')
        OR source_row.payload->>'purpose' IS DISTINCT FROM
            (CASE source_row.role WHEN 'sensor_quality' THEN 'assess_sensor_health'
            ELSE 'assess_event_and_location' END)
        OR source_row.state NOT IN ('SUCCEEDED','ABSTAINED')
        OR coalesce(source_row.payload->'result','null'::jsonb) = 'null'::jsonb
    THEN RAISE EXCEPTION 'reuse_ancestry_conflict'; END IF;
    IF EXISTS (SELECT 1 FROM subsea.reuse_bindings b JOIN subsea.tasks t
        ON (t.tenant_id,t.site_id,t.id)=(b.tenant_id,b.site_id,b.task_id)
        WHERE b.tenant_id=NEW.tenant_id AND b.site_id=NEW.site_id
        AND b.parent_id=NEW.parent_id AND t.role=source_row.role)
    THEN RAISE EXCEPTION 'invalid_reuse_set'; END IF;
    IF source_row.role='event_diagnosis' THEN
        SELECT t.* INTO quality_row FROM subsea.reuse_bindings b JOIN subsea.tasks t
            ON (t.tenant_id,t.site_id,t.id)=(b.tenant_id,b.site_id,b.task_id)
            WHERE b.tenant_id=NEW.tenant_id AND b.site_id=NEW.site_id
            AND b.parent_id=NEW.parent_id AND t.role='sensor_quality';
        IF quality_row.id IS NULL OR quality_row.root_id <> source_row.root_id
            OR NOT EXISTS (SELECT 1 FROM subsea.tool_receipts
                WHERE tenant_id=NEW.tenant_id AND site_id=NEW.site_id
                AND task_id=source_row.id AND payload->>'name'='task.result'
                AND payload->'arguments'->>'task_id'=quality_row.id
                AND payload->>'error' IS NULL AND payload->'result' <> 'null'::jsonb)
        THEN RAISE EXCEPTION 'reuse_dependency_not_consumed'; END IF;
    END IF;
    RETURN NEW;
END $$;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['replays','observations','windows','episodes','tasks',
        'events','monitor_leases','tool_receipts','attempts','model_receipts',
        'control_requests','reuse_bindings']
    LOOP
        EXECUTE format('ALTER TABLE subsea.%I ENABLE ROW LEVEL SECURITY',t);
        EXECUTE format('ALTER TABLE subsea.%I FORCE ROW LEVEL SECURITY',t);
        EXECUTE format('DROP POLICY IF EXISTS scoped ON subsea.%I',t);
        EXECUTE format('CREATE POLICY scoped ON subsea.%I USING
            (tenant_id = nullif(current_setting(''subsea.tenant_id'',true),'''')
             AND site_id = nullif(current_setting(''subsea.site_id'',true),''''))
            WITH CHECK
            (tenant_id = nullif(current_setting(''subsea.tenant_id'',true),'''')
             AND site_id = nullif(current_setting(''subsea.site_id'',true),''''))',t);
        EXECUTE format('REVOKE ALL ON subsea.%I FROM PUBLIC, subsea_checkpoint',t);
        EXECUTE format('GRANT SELECT, INSERT ON subsea.%I TO subsea_app',t);
        EXECUTE format('GRANT SELECT ON subsea.%I TO subsea_tools_ro',t);
    END LOOP;
    FOREACH t IN ARRAY ARRAY['observations','windows','events','tool_receipts',
                             'attempts','model_receipts','control_requests','reuse_bindings']
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS immutable ON subsea.%I',t);
        EXECUTE format('CREATE TRIGGER immutable BEFORE UPDATE OR DELETE
            ON subsea.%I FOR EACH ROW EXECUTE FUNCTION subsea.immutable_row()',t);
    END LOOP;
END $$;
DROP TRIGGER IF EXISTS task_guard ON subsea.tasks;
CREATE TRIGGER task_guard BEFORE INSERT OR UPDATE ON subsea.tasks
    FOR EACH ROW EXECUTE FUNCTION subsea.guard_task();
DROP TRIGGER IF EXISTS reuse_guard ON subsea.reuse_bindings;
CREATE TRIGGER reuse_guard BEFORE INSERT ON subsea.reuse_bindings
    FOR EACH ROW EXECUTE FUNCTION subsea.guard_reuse();
REVOKE UPDATE ON subsea.replays, subsea.episodes, subsea.tasks, subsea.monitor_leases
    FROM subsea_app;
GRANT UPDATE (payload,version) ON subsea.replays TO subsea_app;
GRANT UPDATE (payload) ON subsea.episodes TO subsea_app;
GRANT UPDATE (payload,state,version,lease_token,lease_expires_at,model_calls,tool_calls)
    ON subsea.tasks TO subsea_app;
GRANT UPDATE (owner,expires_at) ON subsea.monitor_leases TO subsea_app;
GRANT DELETE ON subsea.monitor_leases TO subsea_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA subsea TO subsea_app;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA subsea FROM subsea_tools_ro, subsea_checkpoint;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA subsea FROM PUBLIC;
GRANT EXECUTE ON FUNCTION subsea.get_provider_failure() TO subsea_app, subsea_tools_ro;
GRANT EXECUTE ON FUNCTION subsea.mark_provider_failure(text,text,text),
    subsea.clear_provider_failure() TO subsea_app;
