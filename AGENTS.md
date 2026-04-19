# EnglishBot project guidance

Read `context/englishbot_handoff.md` before planning or coding.

Project rules:
- This is a Telegram-first learning product, not an AI playground.
- Runtime source of truth is SQLite, not JSON.
- Core learning unit is `learning_item`, not plain word.
- Business logic must stay in `application/`.
- Telegram modules only orchestrate UX.
- Optional AI/TTS/WebApp must not become required for core runtime.
- Prefer extending existing modules over creating new ones.
- Reject overengineering and future-proofing.
- Keep changes minimal and local.
- Use tests as specification.