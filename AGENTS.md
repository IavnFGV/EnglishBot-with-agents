# EnglishBot project guidance

Always read `context/englishbot_handoff.md` and `context/current_state.md` before planning or coding.

## Core rules
- This is a Telegram-first learning product, not an AI playground.
- Runtime source of truth is SQLite, not JSON.
- Core learning unit is `learning_item`, not plain word.
- Business logic must stay in `application/`.
- Telegram modules only orchestrate UX.
- Optional AI/TTS/WebApp must not become required for core runtime.
- Prefer extending existing modules over creating new ones.
- Keep changes minimal and local.
- Reject overengineering and future-proofing.
- Use tests as specification.

## Feature workflow
For implementation tasks:
1. Propose the smallest possible design.
2. Run a complexity review before implementation.
3. Implement only the approved minimal plan.
4. After implementation, run tests relevant to the change.
5. Update:
   - `CHANGELOG.md`
   - `context/current_state.md`

## Documentation update rule
After every completed task:
- append a short entry to `CHANGELOG.md`
- update `context/current_state.md` with the new current capabilities, constraints, and changed files
- keep both files concise and factual