# Changelog

## 2026-04-19
- Moved role storage out of Telegram `users` and into a separate `user_profiles` entity so product-level profile fields can grow independently from Telegram transport metadata.
- Relaxed invite join behavior so a `teacher` can consume their own invite code for self-testing or future self-assignment flows without losing the `teacher` role.
- Added minimal teacher-student invite binding: SQLite bootstraps `user_profiles`, `invites`, and `teacher_student_links`; `/invite` generates one-time codes for `teacher` users, and `/join <code>` binds one student to one teacher in the MVP.
- Added focused persistence and handler tests covering invite creation, successful join, invalid or reused codes, and duplicate student-link rejection, and listed `pytest` in `requirements.txt` for the new automated tests.
- Added a minimal async Telegram bot package with `/start`, `.env` token loading, INFO logging, and basic error logging for local and devcontainer runs.
- Added a root `.gitignore` for local secrets, Python cache files, virtual environments, logs, IDE artifacts, and local SQLite databases.
- Migrated the minimal Telegram runtime from `python-telegram-bot` to `aiogram 3.x` with `Dispatcher` + `Router`, long polling, and the same `/start -> Привет` behavior.
- Extended the minimal aiogram bot with one `/start` inline button, one callback handler returning `Кнопка нажата`, and one plain text echo handler replying with `Ты написал: <text>`.
- Added minimal SQLite persistence for Telegram users and regular text messages, plus a `/me` command that shows the saved user id and message count.
- Clarified `requirements.txt`: runtime depends on `aiogram` and `python-dotenv`, while SQLite uses the Python standard library and needs no separate package.
- Added a low-level SQLite interaction log with explicit `in/out` direction and event types, so incoming commands/text/callbacks and outgoing bot messages are all visible in one table.
- Moved interaction logging out of handler logic and onto aiogram-wide hooks: incoming updates are logged through `dispatcher.update.outer_middleware(...)`, and outgoing Telegram API calls are logged through bot session middleware.
- Split the aiogram audit hooks into a dedicated `englishbot/audit.py` module and moved singleton `router`/`dispatcher` setup into `englishbot/runtime.py` so `bot.py` stays focused on handlers and startup.
- Removed the separate `messages` table and switched `/me` message counting to the low-level `interactions` audit log; startup now drops the obsolete `messages` table if it exists.
