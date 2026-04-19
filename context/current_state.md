# Current State

- Repository currently contains a minimal runnable Telegram bot foundation at `englishbot/`.
- Entry point is `python -m englishbot`.
- Runtime uses long polling with `aiogram 3.x`.
- `/start` replies with `Привет`.
- `/start` also includes one inline button labeled `Нажми меня`.
- Pressing the inline button triggers a callback handler that replies with `Кнопка нажата`.
- Plain text messages are echoed back as `Ты написал: <text>`.
- Configuration is read from `TELEGRAM_BOT_TOKEN`, with `.env` support via `python-dotenv`.
- If the bot token is missing, startup fails with a clear `RuntimeError`.
- Logging is configured at INFO level, and update-handling exceptions are logged through an aiogram router error handler.
- Repository now includes a root `.gitignore` covering local env files, Python caches, virtual environments, logs, IDE files, and local SQLite databases.
- Current bot structure stays minimal and explicit: `englishbot/config.py` loads `.env` and validates `TELEGRAM_BOT_TOKEN`; `englishbot/bot.py` defines one `Router`, one `/start` handler with inline keyboard, one callback handler, one plain text message handler, one error logger, and aiogram polling startup.
- Changed files for the current bot slice: `englishbot/bot.py`, `CHANGELOG.md`, `context/current_state.md`.
