CREATE OR REPLACE FUNCTION subsea.guard_knowledge_pin() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, subsea AS $$
DECLARE parent_packet jsonb;
BEGIN
    IF TG_OP='UPDATE' AND coalesce(NEW.payload->'knowledge_packet', 'null'::jsonb)
        IS DISTINCT FROM coalesce(OLD.payload->'knowledge_packet', 'null'::jsonb)
    THEN RAISE EXCEPTION 'task_identity_conflict'; END IF;
    IF TG_OP='INSERT' AND NEW.parent_id IS NOT NULL THEN
        SELECT coalesce(payload->'knowledge_packet', 'null'::jsonb) INTO parent_packet
        FROM subsea.tasks WHERE tenant_id=NEW.tenant_id AND site_id=NEW.site_id
            AND id=NEW.parent_id;
        IF coalesce(NEW.payload->'knowledge_packet', 'null'::jsonb)
            IS DISTINCT FROM parent_packet
        THEN RAISE EXCEPTION 'task_identity_conflict'; END IF;
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS knowledge_pin ON subsea.tasks;
CREATE TRIGGER knowledge_pin BEFORE INSERT OR UPDATE ON subsea.tasks
    FOR EACH ROW EXECUTE FUNCTION subsea.guard_knowledge_pin();
