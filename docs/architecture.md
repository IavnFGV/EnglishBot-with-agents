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
- Learning domain: `vocabulary.py`, `topics.py`, `assets.py`, `exercises.py`, `training.py`
- Teacher/student workflows: `teacher_student.py`, `workspaces.py`, `topic_access.py`, `homework.py`, `teacher_assignments.py`, `teacher_content.py`
- Telegram orchestration: `*_handlers.py`
- Multi-step Telegram UI: `homework_dialog.py`, `teacher_assignment_dialog.py`, `teacher_content_dialog.py`
- Operations: `logging_setup.py`, `build_info.py`, `status_server.py`

## Data ownership boundaries
- SQLite is the runtime source of truth.
- `lexemes` are global vocabulary roots.
- `learning_items` are the main learning units and belong to workspaces.
- `topics` group workspace-owned learning items.
- `assets` plus `learning_item_assets` store media metadata.
- `workspaces` and `workspace_members` define ownership and runtime access.
- Student-facing runtime content is published into student workspaces rather than read live from teacher workspaces.

## Major flows
- Teacher onboarding: `/invite` creates one-time codes; `/join` binds a learner and ensures the shared student workspace exists.
- Teacher authoring: `/teacher_content` edits teacher workspaces, topics, items, translations, and linked assets through aiogram-dialog.
- Assignment creation: direct `/assign` and dialog-based `/create_assignment` both end in persisted homework assignments.
- Topic access: `/granttopic` publishes a teacher topic into the shared student workspace and grants access; learners open it with `/topics`.
- Learner training: `/learn`, homework, and topic launches all create or resume staged training sessions via `training.py`.

## Business logic vs Telegram/UI
- Business logic belongs in focused domain modules under `englishbot/`.
- Telegram handlers and dialogs should only validate transport input, call domain functions, and render UI.
- Bot-facing text belongs in `i18n.py`.
- Command definitions belong in `command_registry.py`.

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
