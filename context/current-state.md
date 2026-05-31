# Current State

## Read order
- Start with `AGENTS.md`.
- Then read `docs/module-map.md`.
- Use `docs/architecture.md` for structural context.
- Open task-specific code and tests from the module map.

## Runtime and entrypoints
- Main entrypoint: `python -m englishbot`.
- Startup is centralized in `englishbot/bootstrap.py`.
- The app loads `.env`, configures logging, writes the startup process environment to logs, initializes/migrates SQLite, seeds starter content, starts the status server, registers Telegram commands, and begins long polling.
- Telegram runtime uses `aiogram 3.x` and `aiogram-dialog`.
- A small internal HTTP status server listens on `0.0.0.0:8080`.

## Implemented product slices
- Telegram-first learner flow with `/start`, `/learn`, `/me`, `/settings`, and `/cancel`.
- Teacher/student onboarding with `/invite` and `/join`.
- Temporary admin bootstrap facade with `/admin` for one env-configured super-admin who can prepare family/team memberships without mandatory invite/join.
- The `/admin` screen now tolerates repeated button presses that produce the same text and keyboard, instead of surfacing Telegram's `message is not modified` error in logs.
- Workspace-based content ownership with `teacher` and `student` workspaces.
- Teacher content editing through `/teacher_content` dialog flows.
- Homework assignments from explicit item ids or teacher topics.
- Learner homework list/overview dialog and resumable homework sessions.
- Topic access grants plus learner `/topics` launch flow.
- Training sessions with staged `easy`, `medium`, and optional `hard` exercises.
- Centralized i18n for bot-facing text with `en`, `ru`, `uk`, and `bg`.
- Workbook export/import for teacher workspaces through Telegram `.xlsx` files.
- Asset registry for linked image/audio metadata, with runtime media stored locally on disk even when entered as remote URLs; the original URL may still be kept in asset metadata for traceability.
- Deployment support with Docker Compose and GitHub Actions.
- The service repo now deploys as a Dockge stack in `/opt/dockge/stacks/englishbot`, while runtime `data`, `logs`, and app-created SQLite backup files live in `/srv/services/englishbot/...` bind mounts on the host.
- Service-owned host scheduled tasks now live in this repo under `scheduled-tasks/`, are registered on deploy via `/usr/local/bin/infra-vps-register-service-scheduled-tasks`, and currently only service already-created backup files by copying them into `/srv/drive-sync/services/englishbot/backups` plus simple retention.
- `chain_of_commands/` now includes a dedicated history prompt for the local-media persistence change so that asset-storage decisions can be replayed from one concise brief.
- `chain_of_commands/` also includes a dedicated history prompt for the student-workspace access-model cleanup so the teacher-student refactor can be replayed from one concise brief.
- `chain_of_commands/` also includes a dedicated history prompt for building a temporary admin/UI bootstrap facade over the current workspace model, aimed at a small family/team setup without mandatory invite/join onboarding.

## Data and ownership constraints
- SQLite is the runtime source of truth.
- Core learning unit is `learning_item`, not plain word.
- `lexemes` stay global; `learning_items`, `topics`, and assets are workspace-scoped through ownership or links.
- Teacher content is authored in teacher workspaces and published into student workspaces for runtime learning.
- Teacher-student grouping now lives in `workspace_members` on `student` workspaces; there is no separate teacher-student link table.
- The admin facade is only a bootstrap layer over the same `workspace_members` model: it does not replace invite/join, publish, or assignment rules.
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
- The admin facade currently trusts one `ENGLISHBOT_ADMIN_TELEGRAM_USER_ID` and is intended only as a temporary small-scale bootstrap path, not a production role system.
- No advanced learner statistics beyond current session and assignment progress.
- No dedicated persisted exercise-instance table; exercises are rebuilt from session state.
- Some learner and topic selection flows still use inline button lists, so treat Telegram UI constraints in `AGENTS.md` as the direction for future cleanup rather than a claim that every legacy screen is already ideal.

## Test and validation shape
- Main test command is `python -m pytest`.
- Coverage is focused by module, especially for bootstrap, command registry, i18n, training, homework, topic access, teacher content, workbook flows, logging, and status server behavior.
- Workbook export preserves canonical remote `image_url` and `audio_url` values even when runtime media has already been downloaded into local storage; export tests now stub remote-media persistence when they only need asset metadata, while dedicated vocabulary/workbook-import tests still cover the actual remote-download path.
- Tests are the best proof of current behavior when docs and older prompts disagree.

## Immediate next work areas supported by repo state
- Tighten older Telegram list screens toward the single-screen UI rules where practical.
- Keep narrowing documentation and task navigation around the module map instead of large historical notes.
- Preserve the current workspace/publish/training boundaries while extending teacher and learner flows.
