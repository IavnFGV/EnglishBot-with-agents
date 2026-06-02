# Architecture

## Runtime entry point
- Local start command: `python -m englishbot`
- `englishbot/__main__.py` calls `englishbot.bootstrap.run()`
- `englishbot/bootstrap.py` owns startup order:
  1. load `.env`
  2. configure logging
  3. load build info
  4. initialize and migrate SQLite
  5. seed starter content
  6. start the internal status server
  7. build the bot, register commands, and start long polling

## Main modules
- Runtime wiring: `bootstrap.py`, `runtime.py`, `bot.py`, `command_registry.py`
- Persistence: `db.py`
- User/i18n: `user_profiles.py`, `i18n.py`, `settings_handlers.py`
- Family-first domain slice: `families.py`
- Learning domain: `vocabulary.py`, `topics.py`, `assets.py`, `exercises.py`, `training.py`
- Family-first workflows: `topic_access.py`, `homework.py`, `teacher_assignments.py`, `teacher_content.py`
- Legacy workspace helpers still on disk during cleanup: `workspaces.py`
- Telegram orchestration: `*_handlers.py`
- Multi-step Telegram UI: `homework_dialog.py`, `teacher_assignment_dialog.py`, `teacher_content_dialog.py`
- Operations: `logging_setup.py`, `build_info.py`, `status_server.py`

## Data ownership boundaries
- SQLite is the runtime source of truth.
- `lexemes` are global vocabulary roots.
- `learning_items` are the main learning units and belong to workspaces.
- `topics` group workspace-owned learning items.
- The new family-first persistence slice also supports family-owned `learning_items` and `topics`, plus dedicated family membership, personal progress, and family homework tables, while some legacy workspace persistence still exists during the rebuild.
- `assets` plus `learning_item_assets` store media metadata.
- `workspaces` and `workspace_members` define ownership, teacher-student grouping, and runtime access.
- Student-facing runtime content is published into student workspaces rather than read live from teacher workspaces.

## Major flows
- Family authoring: `/teacher_content` edits shared family topics, items, translations, and linked assets through aiogram-dialog, while still carrying some workspace-aware code paths during the rebuild.
- Assignment creation: `/create_assignment` persists family homework assignments and still coexists with older workspace assignment persistence during the cleanup phase.
- During the family-first rebuild, the same dialogs can also target family-owned topics and family homework assignments without routing through teacher/student invite or simple-mode bootstrap flows.
- Topic access: `/topics` resolves family-owned shared topics directly from `topics.family_id` plus `topic_items`, while legacy published student-workspace topics still remain readable where they already exist.
- Learner training: `/learn`, homework, and topic launches all create or resume staged training sessions via `training.py`.
- During the family-first rebuild, `training_sessions` can point either to legacy workspace homework (`assignment_id`) or to new family homework (`family_homework_assignment_id`), while the staged exercise engine remains shared.

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
- Sessions, assignments, topic access, workspaces, and content all persist in SQLite.
- Workbook files and Telegram message state are integration surfaces, not primary storage.

## Testing strategy
- The project uses focused `pytest` files by module or flow.
- Domain modules usually have direct unit-style tests.
- Telegram handlers and dialog flows have focused behavior tests without requiring a live bot runtime.
- `python -m pytest` is the canonical suite and is also the CI test command.
