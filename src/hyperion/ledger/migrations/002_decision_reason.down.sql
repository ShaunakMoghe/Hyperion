-- M9: record why a call was denied or held (down).

ALTER TABLE calls DROP COLUMN IF EXISTS decision_reason;
