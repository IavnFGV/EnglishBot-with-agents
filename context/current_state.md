# Current State

- Repository currently contains a minimal runnable Telegram bot foundation at `englishbot/`.
- Entry point is `python -m englishbot`.
- Runtime uses long polling with `python-telegram-bot`.
- `/start` replies with `Привет`.
- Configuration is read from `TELEGRAM_BOT_TOKEN`, with `.env` support via `python-dotenv`.
- If the bot token is missing, startup fails with a clear `RuntimeError`.
- Logging is configured at INFO level, and handler exceptions are logged through a global Telegram error handler.
- Repository now includes a root `.gitignore` covering local env files, Python caches, virtual environments, logs, IDE files, and local SQLite databases.
- Added files: `englishbot/__init__.py`, `englishbot/__main__.py`, `englishbot/config.py`, `englishbot/bot.py`, `requirements.txt`, `.env.example`, `.gitignore`, `CHANGELOG.md`.
