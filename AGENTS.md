# EnglishBot project guidance

Always read `context/englishbot_handoff.md` and `context/current_state.md` before planning or coding.

## Core rules
- This is a Telegram-first learning product, not an AI playground.
- Runtime source of truth is SQLite, not JSON.
- Core learning unit is `learning_item`, not plain word.
- Business logic must stay in `application/`.
- Telegram modules only orchestrate UX.
- All bot-facing textual interactions must go through the centralized i18n layer; do not add new hardcoded user-visible strings in handlers, menus, buttons, or Telegram replies.
- Any new Telegram bot command must be added through `englishbot/command_registry.py`; do not introduce ad-hoc command-name literals outside the centralized command registry.
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
- if the task adds or changes environment variables, update `.env.example` in the same task
- keep both files concise and factual

## Development Rules

- New non-trivial features must be implemented through the agent workflow.
- New responsibilities should be introduced in focused modules instead of growing catch-all files.
- New non-trivial features are considered incomplete without automated tests.
- When adding or changing Telegram commands, update `englishbot/command_registry.py` first and wire handlers/startup from that registry instead of introducing parallel command definitions.
- When adding or changing bot-facing text, add or update centralized i18n keys first and resolve them through the i18n layer instead of embedding literal user-visible strings in Telegram modules.
- Documentation (`CHANGELOG.md` and `context/current_state.md`) must be updated after each completed task.
Как

## Dependency rules:
- Any new import MUST be reflected in requirements.txt
- If a package is used but not listed, add it
- Never assume dependencies are preinstalled
- Any new or changed environment variable MUST be added to `.env.example`

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

  ## Telegram UI / Flow Rules (CRITICAL)

This project uses Telegram as a UI platform, not as a message log.

### Core principle

- One logical screen = one Telegram message (max two if strictly necessary)
- Navigation MUST reuse the same message via `edit_message_text` / `edit_message_reply_markup`

### Forbidden patterns

DO NOT:

- Send multiple messages to represent a single screen
- Leave outdated UI messages in chat
- Render large datasets as inline keyboard button lists
- Mix UI state with message history
- Use message spam instead of state transitions

### Required behavior

- Every interactive flow MUST behave like a UI, not a chat log
- Screen transitions MUST update existing messages
- Handlers MUST store and reuse message_id for UI updates
- Old UI messages SHOULD be deleted when no longer relevant

### Navigation consistency

All flows MUST use consistent buttons:

- Back: `⬅ Back`
- Cancel: `Cancel`
- Navigation: `⬅ Prev` / `Next ➡`
- Actions: `✏ Edit`, `🗑 Archive`, `➕ Create`

Do not invent new labels for the same actions.

### Lists and collections

- Large lists MUST NOT be rendered as inline keyboard buttons
- Use:
  - pagination
  - index-based selection
  - navigation buttons

### Screen design

Each screen MUST:

- have a clear header (Topic, Item, etc.)
- show position (e.g. `Item 1/6`)
- be compact and readable
- not duplicate content across messages

### aiogram-dialog usage

For non-trivial multi-step flows (editing, navigation, creation):

- aiogram-dialog MUST be used
- FSM or manual state handling MUST NOT replace dialog flows
- Dialog defines:
  - current screen
  - transitions
  - UI structure

Simple one-step commands MAY avoid dialogs.

### Responsibility split

- Telegram handlers = UI orchestration only
- Navigation/state = dialog or training domain
- Business logic MUST stay outside Telegram layer

### Goal

The bot must feel like navigating a UI, not reading a chat log.
