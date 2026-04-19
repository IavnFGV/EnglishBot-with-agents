# Changelog

## 2026-04-19
- Added a minimal async Telegram bot package with `/start`, `.env` token loading, INFO logging, and basic error logging for local and devcontainer runs.
- Added a root `.gitignore` for local secrets, Python cache files, virtual environments, logs, IDE artifacts, and local SQLite databases.
- Migrated the minimal Telegram runtime from `python-telegram-bot` to `aiogram 3.x` with `Dispatcher` + `Router`, long polling, and the same `/start -> Привет` behavior.
