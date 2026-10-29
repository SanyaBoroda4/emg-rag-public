-- Additive migration (WO7, Bug D): flag chunks whose note text was written
-- by automation (payment bot, stale-job bot, backfill scripts) rather than a
-- person. Expected match: 238 of 7,194 chunks (3.3%).
--
-- These chunks are NOT excluded from the index — they are legitimate
-- records. The flag is surfaced in retrieval so answer generation can
-- describe them as automated system records instead of human observations
-- (Q26's "went quiet after quote" answers were built entirely from stale-bot
-- boilerplate presented as evidence).
--
-- Idempotent: full re-sync of the flag against the pattern on every run.

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS is_bot_generated boolean
    NOT NULL DEFAULT false;

UPDATE chunks
SET is_bot_generated = (raw_text ~* ('payment bot|backfill|check-bot|'
    'Payment recorded|Payment received|No movement in the job since|'
    'invoice-parsing fix'))
WHERE is_bot_generated IS DISTINCT FROM (raw_text ~* ('payment bot|backfill|'
    'check-bot|Payment recorded|Payment received|'
    'No movement in the job since|invoice-parsing fix'));
