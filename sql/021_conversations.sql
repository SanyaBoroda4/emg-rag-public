-- 021: conversation columns on serve.asks (WO17). Additive, serve schema only.
-- A conversation is a sequence of asks in one browser tab that the
-- rewriter may use as history (last <= 3 completed turns). Rows written
-- before this migration have conversation_id NULL and are shown as
-- single-turn conversations.

ALTER TABLE serve.asks
    ADD COLUMN IF NOT EXISTS conversation_id     uuid,
    ADD COLUMN IF NOT EXISTS rewritten_question  text,     -- what the pipeline actually answered (NULL when standalone)
    ADD COLUMN IF NOT EXISTS standalone          boolean,  -- rewriter's decision (NULL for pre-WO17 rows)
    ADD COLUMN IF NOT EXISTS parent_ask_id       bigint REFERENCES serve.asks (id);

CREATE INDEX IF NOT EXISTS asks_user_conv_asked_at_idx
    ON serve.asks (user_name, conversation_id, asked_at);
