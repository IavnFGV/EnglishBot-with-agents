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
- Owner-managed local setups now also expose `/seed_demo`, which fills the owner family with a small idempotent demo dataset (2 topics, 10 basic words) so family-first learner and teacher UI flows can be exercised immediately after bootstrap; when `ENGLISHBOT_OWNER_TELEGRAM_USER_ID` is configured, the command is shown only to that owner in Telegram command menus and owner-specific `/start` and `/help` text.
- A minimal `/help` command now shows the active family-first command set, so unsupported commands like `/help` no longer fall through as unhandled updates.
- Added global observability for unhandled updates: fallback message handler and UnknownIntent error handler now log at WARNING level.
- Expired `aiogram-dialog` intents now also produce a user-facing recovery message: when a stale inline button hits `UnknownIntent`, the bot warns in logs and tells the user that the screen expired and they should reopen `/start` to begin again.
- Bot-level error handling now also ignores Telegram's exact `message is not modified` no-op globally, so harmless repeated UI edits do not flood logs with stack traces.
- The active family-first persistence layer is now the only live product model: SQLite bootstraps `families`, `family_members`, family-owned `learning_items`, family-owned `topics`, `topic_items`, `user_progress`, `homework_assignments`, and `homework_assignment_items`, with focused helpers in `englishbot/families.py`.
- Plain `/learn` is now family-only on the active path: users train only on family-owned learning items, and users outside a family setup get the normal no-items response instead of a legacy workspace fallback.
- Active `/learn` quiz UI is now dialog-based: the learner card itself runs through `learner_training_dialog.py`, while the staged exercise and session rules stay in `training.py`.
- The same learner quiz dialog shell is now reused for homework-backed training too, so `/learn` and homework share one inline learner control seam instead of split bespoke quiz UIs.
- Learner TTS now lives inside those quiz dialogs: when `ENGLISHBOT_TTS_BASE_URL` is configured, each current-word card can show inline `🔊 Listen` plus `🎤 Voice`, voice changes persist `user_profiles.tts_voice_id`, and the next listen uses the new voice immediately.
- Learner pronunciation audio is now persisted too: one `learning_item` can own multiple local synthesized `voice` variants keyed by `learning_item + voice_id + tts_model_key + source_text_hash`, first listen generates on demand, and later listens reuse the stored local file instead of re-synthesizing.
- TTS stays fail-closed and optional: startup does not health-gate on the external service, quiz flow keeps working when TTS is disabled or unavailable, `/settings` still exposes the saved learner voice, and missing or removed voices fall back to the TTS service default voice.
- That learner TTS message is now treated as part of the active training screen too: the latest pronunciation `voice` message id persists in the training session and is cleaned up automatically on the next word or when the session completes, so chat history does not keep growing with stale audio bubbles.
- Learner-facing training buttons still use the newer child-friendly emoji labels on the active runtime path, while the homework open button has been returned to a plain text label for compatibility and bot-facing text still stays centralized in `englishbot/i18n.py`.
- Learner training question cards now show the linked learning item image when `image_ref` resolves to a usable local runtime file, and `/learn`, `/topics`, and homework-backed training all share that same image-aware renderer.
- Static learner question images now also use a separate Telegram transport cache: linked assets can store cached `photo` `file_id`s in SQLite outside the core asset tables, repeat sends prefer that cache, and stale Telegram ids fail closed by re-uploading the local file and refreshing the cached id.
- That learner photo-cache write path now matches real aiogram send replies too, so local bot runs populate the cache even when Telegram returns the sent `photo` sizes as a tuple-like collection.
- `aiogram-dialog` media now also sits on that same SQLite-backed cache backend through a custom `media_id_storage` passed to `setup_dialogs(...)`, so static teacher-content image previews no longer depend only on dialog-local process-memory media caching.
- If a learner question image is missing, invalid, or Telegram rejects the media render, the flow now falls back safely to the existing text-only question card; the separate homework progress photo remains unchanged.
- Learner homework flows are now family-first end to end: active homework lists, start callbacks, progress snapshots, and training-session completion all run only on `homework_assignments`.
- Learner homework is now reachable from both `/start` and an explicit `/homework` command; the direct command reuses the same family-first homework dialog/runtime path instead of creating a second entry flow.
- The current homework assumption is now explicit in code and prompt docs instead of living only in memory: normal homework word flow is `3 easy` then `2 medium`, assignment boost activates after `4` correct answers in a row across the homework, boosted typed hard answers finish the current word immediately, and homework `Skip hard` clears the boost and returns that same word to its normal staged flow without counting a mistake.
- Homework progress-wheel fill is now step-based instead of status-bucket-based: with the current `3 easy + 2 medium` assumption, each post-answer step fills one more `20%` of the sector, normal completion reaches bright green at `100%`, and boosted hard completion still uses the darker hard-clear green.
- Homework medium `Check` completion is now fail-closed in the UI too: if the assembled jumbled-letters answer finishes the active homework session, the callback still updates the progress/cleanup path and sends the final summary instead of silently no-oping after the session row becomes inactive.
- The focused learner-homework UI tests now exercise family homework directly, so the homework list, overview dialog, and homework start handler no longer rely on invite/join scaffolding for their main coverage.
- The homework-specific `training_handlers` tests now also use family homework directly, so learner progress-photo and homework-summary coverage no longer depends on teacher-student invite setup.
- Homework progress-photo rendering now matches the underlying homework statuses more closely: a word that has only reached the pending `hard` step no longer appears visually identical to a fully completed `done` word before the final hard-clear answer.
- `/topics` is now family-first end to end: family learners open shared family topics directly, without grants, published runtime copies, or `student_topic_access`.
- The focused `/topics` handler tests now also run on family topics directly, so the Telegram topic-picker coverage no longer relies on invite/join scaffolding.
- `/teacher_content` and `/create_assignment` are now family-first on the active runtime path: both entrypoints require family membership and work only against family-owned topics/items.
- The `/teacher_content` topics screen now uses one compact pagination model: `screen_text` stays limited to family name, prompt, and page summary, the duplicated text-topic list is gone, the extra `ScrollingGroup` pager that produced the confusing `1 < 1 > 1` control has been removed, and the real Telegram `Prev`/`Next` callbacks now page correctly with distinct dialog widget ids.
- `/bulk_edit` now provides a hardened family-first `.xlsx` bulk editing path: any family member can export the current family workbook, edit it offline, upload it back, and apply it through a validation-first, mandatory-backup, two-phase import.
- Only one bulk edit session may be active across the whole bot at a time; while it is active, normal commands and callback flows are globally gated, the initiator gets a specialized prompt, and reminder/expiration messages are handled by a small background monitor.
- Large `/bulk_edit` applies now keep the reused control message alive with an explicit in-progress status while the workbook import runs, and the Apply callback is acknowledged immediately so long imports no longer look hung or hit Telegram callback expiry.
- Family workbook import is now explicitly two-phase: after validation the bot must first create a SQLite backup, then prepares remote assets outside the DB write transaction into `assets/import-staging/<type>/`, and only after that runs one short atomic DB apply with no network IO inside the transaction.
- That in-progress `/bulk_edit` status is now phase-aware and row-aware: the reused control message distinguishes backup, prepare, and apply work, shows processed rows versus total rows, and can include the current item text during long family imports.
- Under DEBUG logging, long workbook imports no longer spam raw `PIL.PngImagePlugin` chunk traces, and bot-side progress updates now skip non-critical interaction audit writes if SQLite is temporarily locked by the active import transaction.
- Family workbook import/export is now an explicit projection layer in focused modules (`bulk_edit.py`, `workbook_export.py`, `workbook_import.py`): workbook rows missing from the uploaded file are archived rather than hard-deleted, exported `image_ref` now prefers a ready-to-open public image URL for editor convenience, and the display-only `image` column now uses a row-local spreadsheet formula like `=IMAGE(G2)`.
- On deployed servers, workbook export now prefers the current `INFRA_STATIC_BASE_URL` when projecting those workbook image URLs from local runtime assets under `/app/assets`, while the original asset `source_url` remains only traceability metadata in SQLite.
- The matching workbook import path now recognizes those exported static URLs as local runtime assets and maps them back to `assets/...` refs without network download, so normal export/edit/import round trips remain stable.
- Exported family workbooks now also pre-size the image preview layout: the `image` column is widened and data rows are taller so spreadsheet image previews are easier to inspect without manual resizing first.
- A guarded emergency backup-restore helper now exists for family bulk-edit incidents, but it is not part of the normal happy path; the intended flow remains validate, backup, prepare, then short atomic apply.
- The assignment topic picker now exposes dialog-compatible topic ids again, so `/create_assignment` no longer crashes on the topic-selection screen with `KeyError: 'id'` during `aiogram-dialog` select rendering.
- The teacher content and assignment flows no longer need starter-content bootstrap or virtual offset ids to reach family data; the focused dialog and handler tests now seed family content directly.
- The active teacher content and assignment dialogs now store family ids directly in dialog state instead of carrying the old workspace-shaped UI flow.
- The teacher-content overview card now safely ignores Telegram's exact `message is not modified` no-op when returning from prompt screens, so family authoring no longer throws on unchanged overview resyncs.
- The focused assignment-dialog handler tests now also run the main topic/words/recipient/confirm path on family content directly, and the family confirm snapshot bug in `teacher_assignments.py` has been fixed.
- The old `teacher_student.py` invite helper, `simple_mode.py`, and their dedicated tests are now deleted.
- The active registered command list is now family-first plus owner bootstrap support: `/start`, `/help`, `/learn`, `/homework`, `/me`, `/settings`, `/cancel`, `/create_assignment`, `/seed_demo`, `/topics`, `/teacher_content`, and `/bulk_edit`.
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
- Asset registry for linked image/audio metadata, with runtime media stored locally on disk even when entered as remote URLs; `local_path` remains the runtime source of truth, `source_url` is retained only as optional traceability metadata, workbook-imported remote assets now land in clear persistent imported folders like `assets/images/imported/` and `assets/audio/imported/` after staging, and deploy now copies the repo-owned `assets/images/no-image.png` placeholder into the host static-assets mount so fresh VPS installs keep the teacher-content image fallback without extra startup logic.
- Telegram `file_id` reuse is now an explicit cache-only persistence layer keyed by asset and media kind (`photo` plus persisted synthesized `voice` today, `audio` ready too); it accelerates delivery but does not replace local files as runtime truth.
- That runtime placeholder is now tracked directly in git at `assets/images/no-image.png`, and deploy fails closed with an explicit error if the checked-out repo on the VPS ever lacks that source file.
- Deployment support with Docker Compose and GitHub Actions.
- The service repo now deploys as a Dockge stack in `/opt/dockge/stacks/englishbot`, while runtime `data`, `logs`, and app-created SQLite backup files live in `/srv/services/englishbot/...` bind mounts on the host and runtime assets live in `/srv/service-static/englishbot`.
- The deploy workflow now bootstraps privileged host paths under `/opt/dockge` and `/srv/...` with `sudo`, then keeps repo git operations and `docker compose` in the stack directory as the normal SSH user.
- The Docker Compose app service now also reads `/srv/services/englishbot/infra-runtime.env`, so infra-managed public/static base URLs are available inside the running bot container in addition to the checked-in `.env`.
- The deploy workflow also emits explicit directory-state logs for the stack, data, and sync paths so failed VPS runs show whether directories already existed, were created, and what ownership they ended up with.
- The GitHub Actions SSH deploy script now consistently uses the declared `REGISTER_HELPER` variable for the final infra service-registration step, so deploy no longer aborts after a successful `docker compose up -d --build` because of an unset helper variable name.
- Scheduled-task registration now relies only on `SERVICE_NAME` and `SERVICE_DIR` when calling `/usr/local/bin/infra-vps-register-service-scheduled-tasks`; the helper resolves the service-owned `scheduled-tasks/` source from the stack directory itself.
- Service-owned host scheduled tasks now live in this repo under `scheduled-tasks/`, are registered on deploy via `/usr/local/bin/infra-vps-register-service-scheduled-tasks`, and currently only service already-created backup files by copying them into `/srv/drive-sync/services/englishbot/backups` plus simple retention.
- The host backup-maintenance task now emits concise UTC step logs for observability: each run reports start/finish, source/sync paths, source file count before sync, copied-file count, and whether retention pruning was skipped or trimmed files in each directory.
- Task config files under `scheduled-tasks/*.env` are shell-sourced by infra, so values containing spaces, such as cron expressions, must be quoted.
- `chain_of_commands/` now includes a dedicated history prompt for the local-media persistence change so that asset-storage decisions can be replayed from one concise brief.
- `chain_of_commands/` also includes a dedicated history prompt for the student-workspace access-model cleanup so the teacher-student refactor can be replayed from one concise brief.
- `chain_of_commands/047-family-first-rebuild.md` now captures the full family-first rebuild brief so the whole simplification wave can be replayed from one prompt instead of reconstructing it from many commits.
- `chain_of_commands/048-owner-managed-family-access.md` now captures the owner-only privacy layer for local family bootstrap and the technical `/add_family <telegram_user_id>` flow.
- `chain_of_commands/049-local-demo-seeding-and-noop-ui-guard.md` now captures the local-owner polish slice: `/seed_demo` demo bootstrap plus exact Telegram no-op edit guards for both focused dialogs and global bot error handling.
- `chain_of_commands/050-unknown-intent-recovery-notice.md` now captures the expired-dialog recovery slice for `UnknownIntent` logging plus user-facing restart guidance.
- `chain_of_commands/051-family-bulk-edit-via-xlsx.md` now captures the planned return of workbook-based bulk editing from project history, adapted to the current family-first runtime with one global bulk-edit session, bot-wide gating, backup-before-apply, archive-on-missing, and a display-only `image` column exported as a Google Sheets `IMAGE()` formula next to `image_ref`.
- `chain_of_commands/052-bulk-edit-two-phase-import-and-recovery.md` now captures the next planned bulk-edit hardening slice: mandatory backup before processing, remote asset preparation outside the DB write transaction, short atomic DB apply, phase-aware Telegram progress, and a guarded backup-restore fallback for emergency recovery only.
- `chain_of_commands/057-explicit-homework-command.md` now captures the next learner-entry slice: add a visible `/homework` command that opens the existing family-first homework flow directly instead of routing users back through `/start` as the only clear entrypoint.
- `chain_of_commands/058-internal-tts-service-integration.md` now captures the next optional learner-audio slice: integrate the separate internal-only TTS service into the active family-first learner flow with a minimal `Listen` action, persisted user voice selection, optional config wiring, and fail-closed behavior that never makes TTS a required core runtime dependency.
- `chain_of_commands/059-persisted-tts-audio-variants-and-telegram-cache.md` now captures the next learner-TTS UI slice: move active `/learn` quiz UI onto `aiogram-dialog` and embed a reusable inline `Listen + Voice` learner control block into both `learn` and homework quiz surfaces so voice can be switched directly on the current word.
- `chain_of_commands/060-persisted-tts-audio-variants-and-telegram-cache.md` now captures the follow-up storage slice: persist multiple synthesized TTS variants per `learning_item`, distinguish them by voice/model/text identity, and keep Telegram `file_id` reuse as a separate transport cache above those local files.
- `chain_of_commands/061-workbook-export-static-image-urls.md` now captures the workbook-export static-URL slice: keep original remote image URLs only as traceability metadata in SQLite, load infra-managed public/static base URLs into runtime, and export workbook image previews through the current nginx static path for deployed servers.
- `chain_of_commands/053-learner-flow-training-image-cards.md` now captures the learner-flow image-card slice: render linked learning item images in training question cards when available, keep the Telegram screen compact, and fall back safely to text-only questions if an image cannot be shown.
- `chain_of_commands/055-asset-storage-model-simplification.md` now captures the next storage-cleanup slice for imported media: treat the current local workbook-import layout as safe to reshape and reimport, preserve local files as the runtime source of truth, collapse redundant folder/file clutter, and replace misleading `.bin` plus long random quasi-temp permanent-path naming with a clearer asset-id-based model.
- `chain_of_commands/056-telegram-file-id-cache-layer.md` now captures the next Telegram transport-cache slice: add a separate asset-linked `file_id` cache table outside the core learning data model, reuse cached media ids for static learner images first, and keep the same layer ready for future `audio` and `voice` reuse in TTS-backed flows.
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
