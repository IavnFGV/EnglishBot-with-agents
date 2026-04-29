# EnglishBot repository guidance

## Project overview
- `englishbot` is a Telegram-first English learning bot built as a modular monolith on `aiogram`.
- Runtime source of truth is SQLite.
- Core learning unit is `learning_item`.
- Teacher authoring and learner runtime stay separated by workspace boundaries.

## Read this first
Before planning or coding, read these files in order:
1. `AGENTS.md`
2. `docs/module-map.md`
3. `docs/architecture.md`
4. `context/current-state.md`

Read `context/englishbot_handoff.md` only when the task explicitly needs historical context, terminology background, or older target-design notes.

## Mandatory workflow for Codex agents
1. Confirm the smallest possible change.
2. Review complexity before implementation.
3. Read only the task-specific files listed in `docs/module-map.md`.
4. Keep changes local. Prefer extending an existing focused module over adding a new one.
5. Run the narrowest relevant automated tests.
6. After every completed task, update:
   - `CHANGELOG.md`
   - `context/current-state.md`
   - `.env.example` if environment variables changed

## Setup, test, and run
- Install dependencies: `pip install -r requirements.txt`
- Run all tests: `python -m pytest`
- Run one test file: `python -m pytest tests/test_training.py`
- Start the bot locally: `python -m englishbot`
- Bot token source: `.env` via `TELEGRAM_BOT_TOKEN`

## Architecture boundaries
- Business logic belongs in focused modules under `englishbot/` such as `training.py`, `homework.py`, `topics.py`, `topic_access.py`, `teacher_content.py`, `workbook_import.py`, and `workbook_export.py`.
- Telegram/UI orchestration belongs in `*_handlers.py` and `*_dialog.py`.
- `englishbot/bot.py` wires handlers, dialogs, and command registration.
- `englishbot/bootstrap.py` owns startup order.
- `englishbot/db.py` owns SQLite bootstrap, migrations, and shared persistence helpers.
- Do not reintroduce product logic into Telegram handlers.
- Do not treat JSON, workbook files, or Telegram message state as runtime source of truth over SQLite.

## Coding rules
- This is a Telegram-first learning product, not an AI playground.
- All bot-facing text must go through `englishbot/i18n.py`.
- Any new or changed Telegram command must be defined in `englishbot/command_registry.py` first.
- Optional AI, TTS, WebApp, or deployment extras must not become required for core runtime.
- Prefer ASCII unless the file already uses Unicode intentionally.
- Keep comments short and only where they help.
- New non-trivial behavior requires focused automated tests.
- New imports must be reflected in `requirements.txt`.
- Do not claim a feature is implemented unless code or tests prove it.

## Telegram UI rules
- Treat Telegram as a UI, not a message log.
- One logical screen should reuse one message, or two only when strictly necessary.
- Prefer `edit_message_text` or `edit_message_reply_markup` over sending new navigation messages.
- Large collections should use pagination or index-based selection, not giant inline button walls.
- Non-trivial multi-step flows should use `aiogram-dialog`.
- Telegram handlers should orchestrate UI only; business rules stay in domain modules.

## Documentation update rules
- `context/current-state.md` is the concise source of truth for current repository state.
- Keep `docs/architecture.md` stable and structural.
- Keep `docs/module-map.md` task-oriented and easy to scan.
- Do not duplicate the same project summary across many files.
- Historical notes should be marked clearly instead of mixed into current-state docs.

## Token-saving navigation rules
- Start from `docs/module-map.md` and open only the files listed for the task area.
- Prefer reading tests for the task area before scanning unrelated modules.
- Use `context/englishbot_handoff.md` only if current docs do not answer the question.
- Avoid full-repository scans unless the module map is clearly missing the area.

## Do not read unless explicitly relevant
- `chain_of_commands/`
- `context/englishbot_handoff.md`
- `context/current_state.md` except as a compatibility pointer
- `logs/`
- `.pytest_cache/`
- `.git/`
- generated SQLite backup folders such as `workbook_import_backups/`
- `assets/images/teacher-content/` and other binary assets unless the task is about media handling

## Hard navigation constraints
- Full repository scans are forbidden unless the module map is missing the area.
- Read only the files listed in docs/module-map.md for the task area.
- Do not read all tests; only task-specific ones.
- If unsure, do not expand scope.


## Current state constraints
- context/current-state.md must stay under ~150 lines.