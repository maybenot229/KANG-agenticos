-- 0007_notification_queue.sql — the durable notification work item.
--
-- Constitutional home: docs/adr/005-notification-queue-schema.md (accepted
-- shape), 15_EVENT_BUS §6.2 (the ruling this table makes implementable: the
-- queue row is the durable work item, `notification.requested` is only an
-- accelerant — a lost event costs latency, never a lost notification),
-- 09_UI §9 / 05_AGENTS §13 (the priority ladder this enum mirrors),
-- 12_API §13 (`notification.list/ack`: acking is a command, and **acks never
-- delete history** — hence additive stamps beside a preserved row, never an
-- overwriting state field), 12_API §12 (`explain.notification` needs
-- correlation_id to thread through).
--
-- NO SYNC QUARTET, deliberately (ADR-005 Option B). A notification's state —
-- was this shown on this screen, did Kang ack it here — is per-device
-- operational truth, not synchronizable domain truth. Same call, same
-- reasoning as 0002_held_action.sql ("a confirmation belongs to the device
-- that asked") and 0004_api.sql's invocation/idempotency_key/session.
-- Whether acking on one device clears it on another is 15 §15.2's RESERVED
-- cross-device hazard, which 16_SYNC owns; adding the quartet here would
-- answer that open question by accident.

CREATE TABLE notification (
  id             TEXT PRIMARY KEY,     -- UUIDv7
  priority       TEXT NOT NULL CHECK (priority IN
                   ('critical','attention','digest','silent')),
  principal      TEXT NOT NULL,        -- who caused it (SEC-006: attributable)
  correlation_id TEXT NOT NULL,        -- threads to explain.notification (12 §12)
  entity_refs    TEXT NOT NULL,        -- JSON [{kind,id}] for deep-linking
  payload        TEXT NOT NULL,        -- JSON: what to render
  state          TEXT NOT NULL DEFAULT 'queued' CHECK (state IN
                   ('queued','delivered','batched','suppressed','acked')),
  created_at     TEXT NOT NULL,
  delivered_at   TEXT,                 -- additive stamp; never clears the row
  acked_at       TEXT                  -- additive stamp; 12 §13's "acks never
                                       --   delete history", in the schema
);

-- Consumer: the notifier's drain sweep — undelivered work, oldest first
-- (15 §6.2's catch-up path, which is what makes the event an accelerant
-- rather than the work item).
CREATE INDEX idx_notification_queued ON notification(state, created_at)
  WHERE state = 'queued';

-- Consumer: the attention beacon's unacked count (09_UI §9 — one indicator
-- with a count, never a badge-per-feature carnival).
CREATE INDEX idx_notification_unacked ON notification(state, priority)
  WHERE acked_at IS NULL;
