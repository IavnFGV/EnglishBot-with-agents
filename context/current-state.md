# Current State

## Read order
- Start with `AGENTS.md`.
- Then read `docs/module-map.md`.
- Use `docs/architecture.md` for structural context.
- Open task-specific code and tests from the module map.

## Runtime and entrypoints
- Main entrypoint: `python -m englishbot`.
- Startup is centralized in `englishbot/bootstrap.py`.
- The app loads `.env`, configures logging, initializes/migrates SQLite, seeds starter content, starts the status server, registers Telegram commands, and begins long polling.
- Telegram runtime uses `aiogram 3.x` and `aiogram-dialog`.
- A small internal HTTP status server listens on `0.0.0.0:8080`.

## Implemented product slices
- Telegram-first learner flow with `/start`, `/learn`, `/me`, `/settings`, and `/cancel`.
- Teacher/student onboarding with `/invite` and `/join`.
- Workspace-based content ownership with `teacher` and `student` workspaces.
- Teacher content editing through `/teacher_content` dialog flows.
- Homework assignments from explicit item ids or teacher topics.
- Learner homework list/overview dialog and resumable homework sessions.
- Topic access grants plus learner `/topics` launch flow.
- Training sessions with staged `easy`, `medium`, and optional `hard` exercises.
- Centralized i18n for bot-facing text with `en`, `ru`, `uk`, and `bg`.
- Workbook export/import for teacher workspaces through Telegram `.xlsx` files.
- Asset registry for linked image/audio metadata.
- Deployment support with Docker Compose and GitHub Actions.
- Deploy docs now explicitly require VPS secrets, a manual server-side `.env`, and keep nginx/HTTPS ownership in `/opt/infra` while this repo deploys only `/opt/services/englishbot`.

## Data and ownership constraints
- SQLite is the runtime source of truth.
- Core learning unit is `learning_item`, not plain word.
- `lexemes` stay global; `learning_items`, `topics`, and assets are workspace-scoped through ownership or links.
- Teacher content is authored in teacher workspaces and published into student workspaces for runtime learning.
- Assignments and training sessions are snapshot-oriented; live teacher edits must not rewrite in-flight learner state.
- `workspace_members` is the access source of truth for runtime visibility.

## Code boundaries
- Business logic lives in focused modules under `englishbot/`.
- Telegram orchestration lives in `*_handlers.py` and `*_dialog.py`.
- `englishbot/bot.py` wires routers, dialogs, and command registration.
- `englishbot/db.py` owns schema bootstrap, migrations, and shared persistence helpers.
- Bot-facing strings must go through `englishbot/i18n.py`.
- New commands must be added through `englishbot/command_registry.py`.

## Important current limitations
- No web app, webhook runtime, or required AI/TTS dependency in core flows.
- No diff-based publish sync, content versioning, or back-sync from student workspaces.
- No hard delete lifecycle for learning content.
- No Google Sheets integration; workbook flow is local `.xlsx` only.
- No deep-link driven navigation.
- No advanced learner statistics beyond current session and assignment progress.
- No dedicated persisted exercise-instance table; exercises are rebuilt from session state.
- Some learner and topic selection flows still use inline button lists, so treat Telegram UI constraints in `AGENTS.md` as the direction for future cleanup rather than a claim that every legacy screen is already ideal.

## Test and validation shape
- Main test command is `python -m pytest`.
- Coverage is focused by module, especially for bootstrap, command registry, i18n, training, homework, topic access, teacher content, workbook flows, logging, and status server behavior.
- Tests are the best proof of current behavior when docs and older prompts disagree.

## Immediate next work areas supported by repo state
- Tighten older Telegram list screens toward the single-screen UI rules where practical.
- Keep narrowing documentation and task navigation around the module map instead of large historical notes.
- Preserve the current workspace/publish/training boundaries while extending teacher and learner flows.
