-- 053: the design skill an App Builder run is given.
--
-- Set when an agent that has the Impeccable skill ticked starts a build or a
-- change (routes_code -> design_skill.for_agent). NULL is every build before
-- this and every build started from the App Builder page, and such a build
-- runs exactly as it always has. A column rather than a marker in the
-- description: retries and resumes reload the row, so the mark survives
-- them, and the person's own words stay untouched.
ALTER TABLE tasks.items ADD COLUMN IF NOT EXISTS design_skill TEXT;
