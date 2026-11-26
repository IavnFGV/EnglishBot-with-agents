# Current State

Concise source of truth for what the repository does today. History lives in `CHANGELOG.md` and git; the full-featured pre-simplification state is tagged `v1.0-full`.

## Scope
- A home bot for one family (three users): word repetition plus drilling the tutor's homework.
- Keep it simple: no high-availability, rollback, or multi-tenant work.

## Runtime and entrypoints
- Entrypoint: `python -m englishbot`; startup order lives in `englishbot/bootstrap.py`.
- Startup loads `.env`, configures logging (secrets redacted), loads build info, initializes/migrates SQLite, starts the status server, registers commands, and starts long polling.
- Telegram runtime: `aiogram 3.x` plus `aiogram-dialog`.
- The internal stdlib HTTP server on `0.0.0.0:8080` serves `/healthz`, build metadata, the learner Mini App (`/mini-app`), and the dictionary web editor (`/mini-app/editor`).
- Deploy: GitHub Actions on `main` runs tests, then deploys over SSH (host fingerprint verified) to a Dockge stack; see `docs/deploy.md`. Dependabot PRs that pass tests auto-merge.

## Commands
Defined in `englishbot/command_registry.py`. The Telegram menu shows five, with descriptions per interface language: `/learn`, `/homework`, `/topics`, `/teacher_content`, `/settings`. These also work when typed: `/start`, `/help`, `/version`, `/me`, `/cancel`, `/create_assignment` (old words-only assignment dialog), `/seed_demo` and `/add_family` (owner only).

## Family and access
- Family-first model: `families`, `family_members`, family-owned `learning_items` and `topics`, personal `user_progress`, and family homework.
- With `ENGLISHBOT_OWNER_TELEGRAM_USER_ID` set, only the owner auto-creates a `Home` family; others are added with `/add_family <telegram_user_id>`.
- `/seed_demo` fills the owner family with a small idempotent demo dataset.

## Learning
- `/learn`, `/topics`, and homework create or resume a persisted training session through `training.py`.
- Modes `easy` (choose), `medium` (assemble letters), `hard` (type). One correct answer completes a word; hard-mode Help switches that word to medium and records assistance.
- Wrong words come back after the others; three wrong answers defer a word for this round. Summaries report completed, deferred, and assisted counts.
- `/learn` picks words needing review, then unseen words, then the oldest answered, with random ties.
- Telegram quiz UI is one `aiogram-dialog` shell (`learner_training_dialog.py`) shared by `/learn` and homework. Question cards show the item image when available and fall back to text.
- Optional TTS (`ENGLISHBOT_TTS_BASE_URL`): inline Listen and Voice buttons, voice saved per user, synthesized audio persisted per item/voice/model/text hash (a missing file is re-synthesized), stale voice messages cleaned up. Voice messages are captioned with the voice name. Ryan uses `en_US-ryan-high` in tts-service.
- Optional learner Mini App (`ENGLISHBOT_MINI_APP_URL`): same SQLite session as Telegram, Telegram `initData` verified server-side, `question_version` rejects stale answers. A wrong answer shows the correct one; the finish screen lists paper tasks left. "Other voice" next to "Listen" replays the word in the next TTS voice without changing settings. Every Listen shows the voice name; the current question's picture and sound are prefetched (the next one during the game animation). Game mode (default) skins every question type: ball game for multiple choice, bridge for jumbled letters, spell for typed answers (after "Help: show letters" the spell scene stays and the letters become tappable runes; the question carries `hinted`). Skins are client-only over the same server actions (`easy`, `set_medium`/`check`, `hard`); `GAME_SKINS` in `app.js` lists skins per type and questions rotate through them. A header button switches to the plain quiz, saved in `localStorage`. Sounds are synthesized with WebAudio. Heroine poses (`HEROINE_POSES` in `mini_app.py`) are server-only files in `assets/images/heroine-game/*.webp`, served to authorized sessions; missing files fall back to the SVG heroine.
- Every answer is logged at INFO with expected vs given text and the decision.

## Homework
- `/homework` and `/start` open the learner homework list; homework is personal, resumable, and complete only when every word is done.
- Homework is assigned from family topics or picked words (`/create_assignment`), or from a homework set (below). The assigner picks the mode.
- Homework sets (`homework_sets.py`, `homework_import_handlers.py`, `ai_extraction.py`):
  - Forwarding tutor messages (text or photos) to the bot collects a set; "🤖 Recognize with AI: words and verbs" sends it to an optional OpenRouter model, which drafts words and irregular verbs (V1/V2/V3 + translation) in one pass.
  - The draft is reviewed in the web editor (`/mini-app/editor?import=<id>`). Saving files new words under topics, reuses known words without duplicates, and can assign homework; the child is notified.
  - The draft can also pick existing dictionary words from any topic, or a whole topic at once (its verbs go to the verbs task); every row has a ✕ to remove it. Drafts are autosaved to the server after every change.
  - Saved sets can be renamed (assignments follow), re-assigned, edited (later assignments only: search a word or add a whole topic inline, ✕ to remove), archived, and restored. Unsaved drafts are listed and can be deleted.
  - A set is an ordered list of tasks (`homework_set_tasks`: `words`, `verbs`, `paper`, `note`) with photos (`homework_set_photos` gallery, `homework_set_task_assets` links). Drafts can be filled by hand without AI.
  - Word pictures: the model returns a picture number and 0-1000 box per word; the server cuts it (`homework_set_photos.role = 'crop'`), the parent can recut or upload in the draft, and saving copies chosen pictures into the dictionary. Saving, cancelling, and the 30-day abandoned-draft cleanup delete unneeded photos and files.
  - Learners see the tasks in `/homework`: paper tasks with photos are ticked off by the learner (`homework_assignment_task_done`); homework completes when its words are drilled (`homework_assignments.words_completed_at`) and every paper task is ticked.
  - Irregular verbs (`verbs.py`): `learning_items.item_type = 'verb'` with V2/V3 in `details_json`. The quiz shows "go — идти" and asks for "went gone": easy offers mistakes of the same verb, medium jumbles both forms, hard accepts any separator and either variant of "was/were". Known verbs are reused by base form; a plain word with the same text stays separate. Phrases and question-answer pairs are future work.
- The editor's "Homework" screen lists all family homework with progress and cancels unfinished ones.
- AI model queue (`ai_models.py`, tables `app_settings`, `ai_model_stats`): only `:free` OpenRouter ids are accepted. The owner-only "Models" screen manages the queue and runs test checks. Models are tried in order. A daily sync drops models that are no longer free and notifies the owner.

## Content authoring
- `/teacher_content` (button "Dictionary and homework") opens the dictionary web editor (`dictionary_editor.py`, `mini_app_static/editor.*`, API `/mini-app/api/editor/`) when the Mini App URL is set. The older Telegram dialog editor is a secondary button and the fallback.
- The web editor edits topics, words (or irregular verbs with V2/V3), translations, and pictures (gallery or link). Pictures are normalized server-side to upright JPEG up to 1024px. Deletes archive rows.

## Heroine pictures (optional)
- `heroine_pictures.py` plus the `heroine-artist` container (`infra/heroine-artist/`: Codex CLI, stdlib worker). They share only `ENGLISHBOT_HEROINE_DIR` (`jobs/`, `results/`, `status.json`, `refs/`); the artist has no secrets or DB.
- Table `heroine_pictures` (queued, ready, failed, approved, skipped). Active words without a picture and never drawn get a job 10 minutes after creation; the editor's word screen can request one with an idea.
- The editor's "🎨 Heroine pictures" screen: use, redraw with an edited scene, or skip. The button counts pictures being drawn and ready; a word's screen and the pictures screen poll every 8 s while one is drawn. Candidates are re-encoded JPEGs in `assets/images/heroine-candidates/`; approving makes one the word's picture.
- A 60-second loop in the bot enqueues, collects results, notifies the requester (or the owner) and alerts the owner once when Codex needs `codex login --device-auth`.

## Media
- `assets` plus `learning_item_assets` hold media metadata; local files are the runtime truth, and `source_url` is only traceability.
- Telegram `file_id`s are cached separately in `telegram_asset_file_cache` (photos and synthesized voice).
- `assets/images/no-image.png` is the tracked placeholder; deploy copies it into the static mount.

## Operations
- `daily_maintenance.py` writes one SQLite backup per UTC day (`daily__YYYY-MM-DD.sqlite3`) and trims the oldest `interactions` rows once the log exceeds about 200 MB (down to about 150 MB).
- `infra/scheduled-tasks/` holds the host task that copies existing backups to the drive-sync folder (newest 30 kept). Task `.env` values containing spaces must be quoted.
- `/version` reports build metadata from `build.env`.
- Unhandled updates and expired dialog intents are logged; users with an expired screen are told to reopen `/start`. Telegram `message is not modified` errors are ignored.

## Data and code constraints
- SQLite is the runtime source of truth; the core learning unit is `learning_item`; `lexemes` stay global.
- Training sessions and assignments snapshot their content; later edits do not rewrite in-flight learner state.
- Business logic lives in domain modules; Telegram glue lives in `*_handlers.py` and `*_dialog.py`.
- Bot-facing text goes through `i18n.py` (`en`, `ru`, `uk`, `bg`); commands go through `command_registry.py`.
- AI, TTS, and the Mini App are optional and must not block core flows.

## Known limitations
- No webhook runtime and no deep-link navigation.
- No hard delete for learning content; deletes archive.
- No learner statistics beyond session and homework progress.
- Some older Telegram list screens still use plain inline button lists.

## Next work
- Remove the Telegram dialog editor and `/create_assignment` once the web editor fully replaces them.
- Homework import beyond words and verbs: phrases and question-answer pairs; analysis and proposed model in `docs/homework-task-types.md`.

## Tests
- `python -m pytest` is the canonical suite and the CI command; tests are focused per module or flow.
