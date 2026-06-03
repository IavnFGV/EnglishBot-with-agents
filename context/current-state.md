# Current State

## Read order
- Start with `AGENTS.md`.
- Then read `docs/module-map.md`.
- Use `docs/architecture.md` for structural context.
- Open task-specific code and tests from the module map.

## Runtime and entrypoints
- Main entrypoint: `python -m englishbot`.
- Startup is centralized in `englishbot/bootstrap.py`.
- The app loads `.env`, configures logging, writes the startup process environment to logs, initializes/migrates SQLite, starts the status server, registers Telegram commands, and begins long polling.
- Telegram runtime uses `aiogram 3.x` and `aiogram-dialog`.
- A small internal HTTP status server listens on `0.0.0.0:8080`.

## Implemented product slices
- Telegram-first learner flow with `/start`, `/learn`, `/me`, `/settings`, and `/cancel`.
- `/start` now supports an owner-managed privacy mode for local bots: if `ENGLISHBOT_OWNER_TELEGRAM_USER_ID` is set, only that owner account auto-bootstraps a `Home` family, while other users are merely registered and can be added later with the technical `/add_family <telegram_user_id>` command.
- Owner-managed local setups now also expose `/seed_demo`, which fills the owner family with a small idempotent demo dataset (2 topics, 10 basic words) so family-first learner and teacher UI flows can be exercised immediately after bootstrap.
- A minimal `/help` command now shows the active family-first command set, so unsupported commands like `/help` no longer fall through as unhandled updates.
- Added global observability for unhandled updates: fallback message handler and UnknownIntent error handler now log at WARNING level.
- Bot-level error handling now also ignores Telegram's exact `message is not modified` no-op globally, so harmless repeated UI edits do not flood logs with stack traces.
- The active family-first persistence layer is now the only live product model: SQLite bootstraps `families`, `family_members`, family-owned `learning_items`, family-owned `topics`, `topic_items`, `user_progress`, `homework_assignments`, and `homework_assignment_items`, with focused helpers in `englishbot/families.py`.
- Plain `/learn` is now family-only on the active path: users train only on family-owned learning items, and users outside a family setup get the normal no-items response instead of a legacy workspace fallback.
- Learner homework flows are now family-first end to end: active homework lists, start callbacks, progress snapshots, and training-session completion all run only on `homework_assignments`.
- The focused learner-homework UI tests now exercise family homework directly, so the homework list, overview dialog, and homework start handler no longer rely on invite/join scaffolding for their main coverage.
- The homework-specific `training_handlers` tests now also use family homework directly, so learner progress-photo and homework-summary coverage no longer depends on teacher-student invite setup.
- `/topics` is now family-first end to end: family learners open shared family topics directly, without grants, published runtime copies, or `student_topic_access`.
- The focused `/topics` handler tests now also run on family topics directly, so the Telegram topic-picker coverage no longer relies on invite/join scaffolding.
- `/teacher_content` and `/create_assignment` are now family-first on the active runtime path: both entrypoints require family membership and work only against family-owned topics/items.
- The teacher content and assignment flows no longer need starter-content bootstrap or virtual offset ids to reach family data; the focused dialog and handler tests now seed family content directly.
- The active teacher content and assignment dialogs now store family ids directly in dialog state instead of carrying the old workspace-shaped UI flow.
- The teacher-content overview card now safely ignores Telegram's exact `message is not modified` no-op when returning from prompt screens, so family authoring no longer throws on unchanged overview resyncs.
- The focused assignment-dialog handler tests now also run the main topic/words/recipient/confirm path on family content directly, and the family confirm snapshot bug in `teacher_assignments.py` has been fixed.
- The old `teacher_student.py` invite helper, `simple_mode.py`, and their dedicated tests are now deleted.
- The active registered command list is now family-first plus owner bootstrap support: `/start`, `/help`, `/learn`, `/me`, `/settings`, `/cancel`, `/create_assignment`, `/seed_demo`, `/topics`, and `/teacher_content`.
- Legacy admin, invite/join, assign/grant, and workbook Telegram handlers have been deleted from the active bot runtime and from the codebase.
- The old `/admin` env config tail is gone too: `.env.example` no longer documents `ENGLISHBOT_ADMIN_TELEGRAM_USER_ID`, and `englishbot/config.py` no longer exposes an admin-id helper.
- The old publish shell is now gone from the active teacher UI too: `teacher_content` no longer exposes publish buttons or publish target screens, and the dead publish/granttopic i18n strings have been removed.
- SQLite bootstrap no longer keeps `workspaces`, `workspace_members`, `invites`, `student_topic_access`, `assignments`, or `assignment_items` on the active schema path, and `training_sessions` now uses only `family_homework_assignment_id` for active homework runtime.
- Teacher content editing through `/teacher_content` dialog flows.
- Homework assignments from family topics or explicit family item selection.
- Learner homework list/overview dialog and resumable homework sessions.
- Learner `/topics` launch flow over shared family topics.
- Training sessions with staged `easy`, `medium`, and optional `hard` exercises.
- Centralized i18n for bot-facing text with `en`, `ru`, `uk`, and `bg`.
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
- `chain_of_commands/047-family-first-rebuild.md` now captures the full family-first rebuild brief so the whole simplification wave can be replayed from one prompt instead of reconstructing it from many commits.
- `chain_of_commands/048-owner-managed-family-access.md` now captures the owner-only privacy layer for local family bootstrap and the technical `/add_family <telegram_user_id>` flow.
- `docs/family-first-rebuild.md` records the approved direction: keep this repository and deploy path, but replace the old workspace/publish-centric product model with a family-first core built around shared family content plus personal progress and homework.

## Data and ownership constraints
- SQLite is the runtime source of truth.
- Core learning unit is `learning_item`, not plain word.
- `lexemes` stay global; active product content now lives in family-owned `learning_items`, `topics`, and linked assets.
- Family learning runtime now reads shared family content directly; publish-era teacher/student workspace runtime is no longer part of active learner or teacher flows.
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
- No deep-link driven navigation.
- No advanced learner statistics beyond current session and assignment progress.
- No dedicated persisted exercise-instance table; exercises are rebuilt from session state.
- Some learner and topic selection flows still use inline button lists, so treat Telegram UI constraints in `AGENTS.md` as the direction for future cleanup rather than a claim that every legacy screen is already ideal.

## Test and validation shape
- Main test command is `python -m pytest`.
- Coverage is focused by module, especially for bootstrap, command registry, i18n, training, homework, topic access, teacher content, logging, and status server behavior.
- Tests are the best proof of current behavior when docs and older prompts disagree.

## Immediate next work areas supported by repo state
- Tighten older Telegram list screens toward the single-screen UI rules where practical.
- Keep narrowing documentation and task navigation around the module map instead of large historical notes.
- Add new family-first product slices on top of the simplified schema instead of reviving removed workspace-era paths.
