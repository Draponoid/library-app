-- Application inserts require sequence USAGE; a complete pg_dump also needs SELECT.
-- Touch only ID sequences owned by application tables (sessions has a token key).
BEGIN;
DO $grants$
DECLARE
    sequence_name text;
    granted integer := 0;
BEGIN
    FOR sequence_name IN
        SELECT pg_get_serial_sequence(format('public.%I', table_name), 'id')
        FROM unnest(ARRAY['authors','books','branches','copies','faculties',
                          'users','loans','audit_events']) AS app(table_name)
    LOOP
        IF sequence_name IS NOT NULL
           AND NOT has_sequence_privilege('labapp', sequence_name, 'SELECT') THEN
            -- pg_get_serial_sequence returns a safely quoted qualified identifier.
            EXECUTE format('GRANT SELECT ON SEQUENCE %s TO labapp', sequence_name);
            granted := granted + 1;
        END IF;
    END LOOP;
    RAISE NOTICE 'Backup sequence privileges checked; missing SELECT grants added: %', granted;
END
$grants$;
COMMIT;
