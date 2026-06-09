-- 019: allow the OUTREACH action_type (idempotent, name-agnostic)
DO $$
DECLARE c text;
BEGIN
  SELECT conname INTO c FROM pg_constraint
   WHERE conrelid = 'tasks.items'::regclass AND contype = 'c'
     AND pg_get_constraintdef(oid) ILIKE '%action_type%';
  IF c IS NOT NULL THEN
    EXECUTE format('ALTER TABLE tasks.items DROP CONSTRAINT %I', c);
  END IF;
  ALTER TABLE tasks.items
    ADD CONSTRAINT items_action_type_check
    CHECK (action_type IN ('RESEARCH','BUILD','INTEGRATE','ASK_USER','OUTREACH'));
END $$;
