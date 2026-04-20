Read:
- context/englishbot_handoff.md
- context/current_state.md
- AGENTS.md

Goal:
Implement import of teacher-workspace content from the workbook .xlsx format using the existing workbook_key-based model and current export contract.

Context:
The repository already supports:
- stable workspace-scoped workbook_key values for topics and learning_items
- confirmed persistence mappings from real code
- workbook export into exactly 3 sheets:
  - topics
  - topic_items
  - learning_items

Workbook export already includes:
- workbook_key as primary identity
- optional DB id columns
- wide translation columns (ru/uk/bg)
- archive flags
- image_ref and audio_ref
- a display-only image column using =IMAGE(...) formula

IMPORTANT:
- image_ref is the source of truth
- image column is display-only and MUST be ignored during import

This slice implements import only.

Scope:
Import one workbook .xlsx into one specified teacher workspace.

Required behavior:

1. Workspace scope:
   - import is allowed only into teacher workspace
   - import into student workspace must fail

2. Identity:
   - match by workbook_key only
   - DB ids (if present) are optional and may be used only for consistency checks

3. Partial upsert:
   - existing rows (same workbook_key) are updated
   - new workbook_key creates new entity
   - missing rows in workbook DO NOT delete anything

4. Archive:
   - is_archived controls archive state
   - archive is never inferred from missing rows

5. Translations:
   - non-empty translation_ru/uk/bg → upsert translation
   - empty translation cell → leave unchanged (no delete)

6. Learning items:
   - lexeme/headword mapping must follow real schema (confirmed in current_state)
   - if headword changes, handle safely without corrupting shared lexemes

7. Topic membership:
   - topic_items defines membership
   - links are added if missing
   - no implicit deletion of existing links
   - any broken reference (missing topic_key or learning_item_key) must fail the whole import

8. Image handling:
   - use image_ref column only
   - ignore image column completely

9. Validation:
   - required sheets must exist
   - required columns must exist
   - duplicate workbook_key in sheet → fail
   - broken references → fail
   - invalid archive values → fail

10. Transaction:
   - import must be atomic
   - either everything is applied or nothing

Constraints:
- do not implement Google Sheets API
- do not implement Telegram commands in this slice
- do not implement student visibility management
- do not implement diff/versioning/sync engine
- do not introduce hard delete
- keep implementation minimal and focused
- do not mix business logic into Telegram layer

Architecture expectations:
- import logic must live in a focused module (e.g. workbook_import.py)
- reuse existing vocabulary/topics logic where possible
- do not turn existing modules into catch-all files

Testing requirements:
- test updating existing topics by workbook_key
- test creating new topics by new workbook_key
- test updating learning_items
- test translation updates (no delete on empty)
- test archive flag behavior
- test topic_items membership updates
- test fail-fast on broken references
- test atomic behavior (partial failure → no changes)
- test ignoring image column
- test teacher workspace restriction
- tests should not depend on Telegram runtime where possible

Documentation:
- update CHANGELOG.md
- update context/current_state.md

Workflow:
1. architect
2. complexity_guard
3. coder
4. complexity_guard

Definition of done:
- workbook .xlsx can be imported into teacher workspace
- workbook_key-based partial upsert works correctly
- topic membership updates safely
- image column is ignored, image_ref is used
- import is atomic
- tests pass
- docs updated