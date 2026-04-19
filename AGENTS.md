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

## Development Rules

- New non-trivial features must be implemented through the agent workflow.
- New responsibilities should be introduced in focused modules instead of growing catch-all files.
- New non-trivial features are considered incomplete without automated tests.
- Documentation (`CHANGELOG.md` and `context/current_state.md`) must be updated after each completed task.
Как

## Dependency rules:
- Any new import MUST be reflected in requirements.txt
- If a package is used but not listed, add it
- Never assume dependencies are preinstalled

## File structure rules

- Do not turn existing files into catch-all files.
- If a feature introduces a new responsibility, create a separate focused file/module.
- For small local changes, prefer modifying the existing file(not more thatn 30-50 lines  and NOT adding new responsibility)
- Avoid both extremes:
  - dumping everything into one file
  - splitting simple logic into too many tiny files
- New files must be connected to existing code with minimal explicit wiring.

## Testing rules

- Every non-trivial feature must include automated tests.
- New persistence logic must be covered by tests.
- New command flows must be covered by tests.
- Tests are required as part of feature completion, not as optional follow-up work.
- Prefer focused tests for the new module(s) instead of broad end-to-end-only coverage.
- A feature is not complete until:
  - code is implemented
  - tests are added
  - relevant tests pass