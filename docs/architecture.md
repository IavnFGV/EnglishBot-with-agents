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
  6. build the bot, register commands, start the daily maintenance task, and start long polling

## Main modules
- Runtime wiring: `bootstrap.py`, `runtime.py`, `bot.py`, `command_registry.py`
- Persistence: `db.py`
- User/i18n: `user_profiles.py`, `i18n.py`, `settings_handlers.py`
- Family-first domain slice: `families.py`
- Learning domain: `vocabulary.py`, `topics.py`, `assets.py`, `exercises.py`, `training.py`
- Family-first workflows: `topic_access.py`, `homework.py`, `learner_homework.py`, `teacher_assignments.py`, `teacher_content.py`
- Homework import and web editor: `homework_sets.py`, `homework_import_handlers.py`, `ai_extraction.py`, `ai_models.py`, `dictionary_editor.py`
- Telegram orchestration: `*_handlers.py`
- Multi-step Telegram UI: `learner_training_dialog.py`, `homework_dialog.py`, `teacher_assignment_dialog.py`, `teacher_content_dialog.py`
- Operations and optional HTTP UI: `logging_setup.py`, `build_info.py`, `audit.py`, `daily_maintenance.py`, `status_server.py`, `mini_app.py`, `mini_app_handlers.py`, `mini_app_static/`

## Data ownership boundaries
- SQLite is the runtime source of truth.
- `lexemes` are global vocabulary roots.
- `learning_items` are the main learning units.
- `topics` group learning items.
- `learning_items` and `topics` are family-owned; `families`, `family_members`, `user_progress`, `homework_assignments`, and `homework_assignment_items` hold membership, personal progress, and homework.
- `homework_sets` and `homework_set_items` hold imported tutor homework (draft, then saved); assignments keep `homework_set_id`.
- `app_settings` and `ai_model_stats` hold the AI model queue and per-model results.
- `assets` plus `learning_item_assets` store media metadata.
- `learning_item_tts_variants` stores persistent synthesized learner-audio variants per `learning_item`, keyed by composed runtime identity such as `voice_id`, `tts_model_key`, and source-text hash, while the linked local `assets` row remains the runtime file truth.
- Telegram transport reuse is a separate cache layer: asset-linked `file_id`s live outside the core asset tables and do not replace local runtime media.

## Major flows
- Family authoring: `/teacher_content` opens the dictionary web editor (`/mini-app/editor`) when the Mini App URL is set; the older aiogram-dialog editor remains as a fallback.
- Homework import: forwarded tutor messages collect a homework set, an optional OpenRouter model drafts words, a person reviews and saves the draft in the web editor, and the set can be assigned as homework.
- Assignment creation: `/create_assignment` persists family homework assignments for family members.
- Topic access: `/topics` resolves family-owned shared topics directly from `topics.family_id` plus `topic_items`.
- Learner training: `/learn`, homework, and topic launches all create or resume training sessions with a persisted chosen mode via `training.py`; the active `/learn` and homework quiz surfaces now render through a shared learner `aiogram-dialog` shell with reusable inline TTS controls.
- Family homework uses `training_sessions.family_homework_assignment_id` as the only active homework session link, while mode, answer, retry, and help rules remain shared.
- The optional Mini App and web editor serve static HTML/CSS/JavaScript and `initData`-authenticated API routes from the existing status-server process. Telegram and HTTP actions both use `training.py` and one SQLite session; `question_version` detects stale answers and `source_topic_id` supports topic resume.

## Business logic vs Telegram/UI
- Business logic belongs in focused domain modules under `englishbot/`.
- Telegram handlers and dialogs should only validate transport input, call domain functions, and render UI.
- Bot-facing text belongs in `i18n.py`.
- Command definitions belong in `command_registry.py`.

## Persistence summary
- Schema bootstrap and migrations live in `db.py`.
- The repository uses SQLite through stdlib `sqlite3`.
- Sessions, homework, topic access, and content all persist in SQLite.
- Telegram media `file_id`s persist in a separate cache table keyed by `asset_id` plus media kind, so transport reuse stays outside the main learning and asset truth model, including persisted synthesized TTS variants.
- Telegram message state and forwarded files are integration surfaces, not primary storage; deleting content archives it instead of hard-deleting it.

## Testing strategy
- The project uses focused `pytest` files by module or flow.
- Domain modules usually have direct unit-style tests.
- Telegram handlers and dialog flows have focused behavior tests without requiring a live bot runtime.
- `python -m pytest` is the canonical suite and is also the CI test command.
