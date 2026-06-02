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
- The first family-first rebuild slice is now implemented in persistence: SQLite now has `families`, `family_members`, family-scoped `learning_items`/`topics` support, `topic_items`, `user_progress`, and `homework_assignments` tables, with focused helpers in `englishbot/families.py`.
- Plain `/learn` now prefers family-owned learning items when the user belongs to a family, instead of falling back to the legacy workspace content source.
- Learner homework flows are now family-first end to end: active homework lists, start callbacks, progress snapshots, and training-session completion all run only on `homework_assignments`.
- The focused learner-homework UI tests now exercise family homework directly, so the homework list, overview dialog, and homework start handler no longer rely on invite/join scaffolding for their main coverage.
- The homework-specific `training_handlers` tests now also use family homework directly, so learner progress-photo and homework-summary coverage no longer depends on teacher-student invite setup.
- `/topics` is now family-first end to end: family learners open shared family topics directly, without grants, published runtime copies, or `student_topic_access`.
- The focused `/topics` handler tests now also run on family topics directly, so the Telegram topic-picker coverage no longer relies on invite/join scaffolding.
- `/teacher_content` and `/create_assignment` are now family-first on the active runtime path: both entrypoints require family membership and work only against family-owned topics/items.
- The focused assignment-dialog handler tests now also run the main topic/words/recipient/confirm path on family content directly, and the family confirm snapshot bug in `teacher_assignments.py` has been fixed.
- The old `teacher_student.py` invite helper, `simple_mode.py`, and their dedicated tests are now deleted; the remaining legacy surface is mostly workbook-domain code and old schema/helpers that are no longer on active product paths.
- The active registered command list is now family-first only: `/start`, `/learn`, `/me`, `/settings`, `/cancel`, `/create_assignment`, `/topics`, and `/teacher_content`.
- Legacy admin, invite/join, assign/grant, and workbook Telegram handlers have been deleted from the active bot runtime and from the codebase.
- The old `/admin` env config tail is gone too: `.env.example` no longer documents `ENGLISHBOT_ADMIN_TELEGRAM_USER_ID`, and `englishbot/config.py` no longer exposes an admin-id helper.
- Teacher content editing through `/teacher_content` dialog flows.
- Homework assignments from family topics or explicit family item selection.
- Learner homework list/overview dialog and resumable homework sessions.
- Learner `/topics` launch flow over shared family topics.
- Training sessions with staged `easy`, `medium`, and optional `hard` exercises.
- Centralized i18n for bot-facing text with `en`, `ru`, `uk`, and `bg`.
- Workbook export/import for teacher workspaces through Telegram `.xlsx` files.
- Asset registry for linked image/audio metadata, with runtime media stored locally on disk even when entered as remote URLs; the original URL may still be kept in asset metadata for traceability.
- Deployment support with Docker Compose and GitHub Actions.
- The service repo now deploys as a Dockge stack in `/opt/dockge/stacks/englishbot`, while runtime `data`, `logs`, and app-created SQLite backup files live in `/srv/services/englishbot/...` bind mounts on the host.
- The deploy workflow now bootstraps privileged host paths under `/opt/dockge` and `/srv/...` with `sudo`, then keeps repo git operations and `docker compose` in the stack directory as the normal SSH user.
- The deploy workflow also emits explicit directory-state logs for the stack, data, and sync paths so failed VPS runs show whether directories already existed, were created, and what ownership they ended up with.
- Scheduled-task registration now relies only on `SERVICE_NAME` and `SERVICE_DIR` when calling `/usr/local/bin/infra-vps-register-service-scheduled-tasks`; the helper resolves the service-owned `scheduled-tasks/` source from the stack directory itself.
- Service-owned host scheduled tasks now live in this repo under `scheduled-tasks/`, are registered on deploy via `/usr/local/bin/infra-vps-register-service-scheduled-tasks`, and currently only service already-created backup files by copying them into `/srv/drive-sync/services/englishbot/backups` plus simple retention.
- Task config files under `scheduled-tasks/*.env` are shell-sourced by infra, so values containing spaces, such as cron expressions, must be quoted.
- `chain_of_commands/` now includes a dedicated history prompt for the local-media persistence change so that asset-storage decisions can be replayed from one concise brief.
- `chain_of_commands/` also includes a dedicated history prompt for the student-workspace access-model cleanup so the teacher-student refactor can be replayed from one concise brief.
- `docs/family-first-rebuild.md` records the approved next direction: keep this repository and deploy path, but replace the workspace/publish-centric product model with a family-first core built around shared family content plus personal progress and homework.

## Data and ownership constraints
- SQLite is the runtime source of truth.
- Core learning unit is `learning_item`, not plain word.
- `lexemes` stay global; active product content now lives in family-owned `learning_items`, `topics`, and linked assets.
- Family learning runtime now reads shared family content directly; publish-era teacher/student workspace runtime is no longer part of active learner flows.
- Assignments and training sessions are snapshot-oriented; live teacher edits must not rewrite in-flight learner state.

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
- The remaining legacy surface is mostly workbook-domain code, old schema baggage, and cleanup-worthy workspace helpers that are no longer on active product paths.
- No advanced learner statistics beyond current session and assignment progress.
- No dedicated persisted exercise-instance table; exercises are rebuilt from session state.
- Some learner and topic selection flows still use inline button lists, so treat Telegram UI constraints in `AGENTS.md` as the direction for future cleanup rather than a claim that every legacy screen is already ideal.

## Test and validation shape
- Main test command is `python -m pytest`.
- Coverage is focused by module, especially for bootstrap, command registry, i18n, training, homework, topic access, teacher content, workbook flows, logging, and status server behavior.
- Workbook export preserves canonical remote `image_url` and `audio_url` values even when runtime media has already been downloaded into local storage; export tests now stub remote-media persistence when they only need asset metadata, while dedicated vocabulary/workbook-import tests still cover the actual remote-download path.
- Tests are the best proof of current behavior when docs and older prompts disagree.

## Immediate next work areas supported by repo state
- Next family-first step is the final delete wave: decide whether workbook import/export survives as an offline maintenance tool or gets removed entirely, then prune the leftover workspace-first helpers and old schema baggage.
- Tighten older Telegram list screens toward the single-screen UI rules where practical.
- Keep narrowing documentation and task navigation around the module map instead of large historical notes.
