-- Per-clone workflow update status.
--
-- workflow_versions.json records one deployed laya_version per template. It
-- cannot say which individual clone of that template failed to take the
-- update, so a clone whose push was rejected by n8n (or whose workflow was
-- deleted in the n8n UI) stayed invisible and was never retried. These two
-- columns hold the last update failure for each clone: a short, user-facing
-- reason and when it happened (db/timeutil.py format). Both are NULL while
-- the clone is up to date. Startup propagation re-pushes every flagged clone
-- and the Settings workflow list shows the reason with an "Update workflow"
-- action.
ALTER TABLE sources ADD COLUMN workflow_update_error TEXT;
ALTER TABLE sources ADD COLUMN workflow_update_failed_at TEXT;
