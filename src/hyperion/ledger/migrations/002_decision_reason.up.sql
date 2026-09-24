-- M9: record why a call was denied or held (up).
--
-- decision_reason is executor state, not ledger evidence: like status, it is
-- excluded from the hash chain on purpose (see store._payload_of).

ALTER TABLE calls ADD COLUMN IF NOT EXISTS decision_reason text;
