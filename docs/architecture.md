# Architecture

## Runtime entry point
- Local start command: `python -m englishbot`
- `englishbot/__main__.py` calls `englishbot.bootstrap.run()`
- `englishbot/bootstrap.py` owns startup order:
  1. load `.env`
  2. configure logging
  3. load build info
  4. initialize and migrate SQLite
  5. start the internal status server
  6. build the bot, register commands, and start long polling

## Main modules
- Runtime wiring: `bootstrap.py`, `runtime.py`, `bot.py`, `command_registry.py`
- Persistence: `db.py`
- User/i18n: `user_profiles.py`, `i18n.py`, `settings_handlers.py`
- Family-first domain slice: `families.py`
- Learning domain: `vocabulary.py`, `topics.py`, `assets.py`, `exercises.py`, `training.py`
- Family-first workflows: `topic_access.py`, `homework.py`, `teacher_assignments.py`, `teacher_content.py`, `bulk_edit.py`, `workbook_export.py`, `workbook_import.py`
- Telegram orchestration: `*_handlers.py`
- Multi-step Telegram UI: `learner_training_dialog.py`, `homework_dialog.py`, `teacher_assignment_dialog.py`, `teacher_content_dialog.py`
- Operations: `logging_setup.py`, `build_info.py`, `status_server.py`

## Data ownership boundaries
- SQLite is the runtime source of truth.
- `lexemes` are global vocabulary roots.
- `learning_items` are the main learning units.
- `topics` group learning items.
- The new family-first persistence slice also supports family-owned `learning_items` and `topics`, plus dedicated family membership, personal progress, and family homework tables; active learner flows now read that family-owned content directly.
- `assets` plus `learning_item_assets` store media metadata.
- Telegram transport reuse is a separate cache layer: asset-linked `file_id`s live outside the core asset tables and do not replace local runtime media.
- The active schema is family-first: content, homework, and progress no longer depend on `workspaces`, `workspace_members`, or starter-content bootstrap tables.

## Major flows
- Family authoring: `/teacher_content` edits shared family topics, items, translations, and linked assets through aiogram-dialog.
- Family bulk editing: `/bulk_edit` exports one family workbook, opens one global gated bulk-edit session, and applies the returned `.xlsx` back into SQLite through a validation-first, backup-first, two-phase import (`prepare` outside the DB write transaction, then short atomic `apply`).
- Assignment creation: `/create_assignment` persists family homework assignments for family members.
- The active authoring and assignment flows resolve directly through family membership without invite/join, grants, or workspace bootstrap.
- Topic access: `/topics` resolves family-owned shared topics directly from `topics.family_id` plus `topic_items`.
- Learner training: `/learn`, homework, and topic launches all create or resume staged training sessions via `training.py`; the active `/learn` and homework quiz surfaces now render through a shared learner `aiogram-dialog` shell with reusable inline TTS controls.
- Family homework uses `training_sessions.family_homework_assignment_id` as the only active homework session link, while the staged exercise engine remains shared.

## Business logic vs Telegram/UI
- Business logic belongs in focused domain modules under `englishbot/`.
- Telegram handlers and dialogs should only validate transport input, call domain functions, and render UI.
- Bot-facing text belongs in `i18n.py`.
- Command definitions belong in `command_registry.py`.
- The registered command set is intentionally limited to family-first commands during the rebuild.
- The active bot wiring in `englishbot/bot.py` no longer imports the old admin, invite/join, assign, grant, or workbook Telegram handlers.

## Persistence summary
- Schema bootstrap and migrations live in `db.py`.
- The repository uses SQLite through stdlib `sqlite3`.
- Sessions, homework, topic access, and content all persist in SQLite.
- Telegram media `file_id`s persist in a separate cache table keyed by `asset_id` plus media kind, so transport reuse stays outside the main learning and asset truth model.
- Bulk edit sessions also persist in SQLite so the bot can enforce one active workbook session globally and recover gating state after restart.
- The active family-first schema no longer bootstraps `workspaces`, `workspace_members`, `invites`, `student_topic_access`, `assignments`, or `assignment_items`.
- Workbook files and Telegram message state are integration surfaces, not primary storage; family workbook apply is backup-first, remote assets are prepared outside the DB write transaction into local staged files, the DB apply remains atomic and short, and missing workbook rows archive family content instead of hard-deleting it.

## Testing strategy
- The project uses focused `pytest` files by module or flow.
- Domain modules usually have direct unit-style tests.
- Telegram handlers and dialog flows have focused behavior tests without requiring a live bot runtime.
- `python -m pytest` is the canonical suite and is also the CI test command.
