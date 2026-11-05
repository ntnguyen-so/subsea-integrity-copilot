CREATE TABLE IF NOT EXISTS subsea.history_documents (
    tenant_id text NOT NULL,
    site_id text NOT NULL,
    corpus_version text NOT NULL,
    id text NOT NULL,
    available_at timestamptz NOT NULL,
    authored_at timestamptz NOT NULL,
    effective_from timestamptz NOT NULL,
    asset_ids text[] NOT NULL,
    scenarios text[] NOT NULL,
    payload jsonb NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS
        (to_tsvector('english', coalesce(payload->>'title','') || ' ' ||
                    coalesce(payload->>'body',''))) STORED,
    PRIMARY KEY (tenant_id, site_id, corpus_version, id)
);
CREATE INDEX IF NOT EXISTS history_full_text
    ON subsea.history_documents USING gin(search_vector);
ALTER TABLE subsea.history_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE subsea.history_documents FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS scoped_history ON subsea.history_documents;
CREATE POLICY scoped_history ON subsea.history_documents
    USING (tenant_id = current_setting('subsea.tenant_id', true)
           AND site_id = current_setting('subsea.site_id', true))
    WITH CHECK (tenant_id = current_setting('subsea.tenant_id', true)
                AND site_id = current_setting('subsea.site_id', true));
REVOKE ALL ON subsea.history_documents FROM PUBLIC, subsea_checkpoint;
GRANT SELECT, INSERT ON subsea.history_documents TO subsea_app;
GRANT SELECT ON subsea.history_documents TO subsea_tools_ro;
DROP TRIGGER IF EXISTS immutable ON subsea.history_documents;
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON subsea.history_documents
    FOR EACH ROW EXECUTE FUNCTION subsea.immutable_row();

CREATE OR REPLACE FUNCTION subsea.guard_history_pin() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, subsea AS $$
DECLARE parent_version text;
BEGIN
    IF TG_OP='UPDATE' AND NEW.payload->>'history_version'
        IS DISTINCT FROM OLD.payload->>'history_version'
        OR TG_OP='UPDATE' AND NEW.payload->>'response_protocol'
        IS DISTINCT FROM OLD.payload->>'response_protocol'
    THEN RAISE EXCEPTION 'task_identity_conflict'; END IF;
    IF TG_OP='INSERT' AND NEW.parent_id IS NOT NULL THEN
        SELECT payload->>'history_version' INTO parent_version
        FROM subsea.tasks WHERE tenant_id=NEW.tenant_id AND site_id=NEW.site_id
            AND id=NEW.parent_id;
        IF NEW.payload->>'history_version' IS DISTINCT FROM parent_version
        THEN RAISE EXCEPTION 'task_identity_conflict'; END IF;
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS history_pin ON subsea.tasks;
CREATE TRIGGER history_pin BEFORE INSERT OR UPDATE ON subsea.tasks
    FOR EACH ROW EXECUTE FUNCTION subsea.guard_history_pin();
