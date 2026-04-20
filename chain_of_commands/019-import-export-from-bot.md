Read:
- context/englishbot_handoff.md
- context/current_state.md
- AGENTS.md

Goal:
Expose teacher-workspace workbook export/import through minimal Telegram/admin flows.

Context:
The repository already supports:
- workbook_key-based teacher-workspace content export
- workbook_key-based teacher-workspace content import
- atomic partial upsert
- workbook validation
- display-only image column ignored on import

This slice adds only the thinnest practical Telegram integration.

Scope:
Add minimal teacher/admin flows for:
- exporting one teacher workspace workbook as .xlsx
- importing one .xlsx workbook into one teacher workspace

Requirements:

1. Access control:
   - only teacher members of the target teacher workspace may export/import
   - export/import for student workspaces must fail clearly

2. Explicit scoping:
   - commands must require explicit teacher_workspace_id
   - no implicit workspace selection

3. Export flow:
   - teacher can request workbook export for one teacher workspace
   - bot returns the generated .xlsx file

4. Import flow:
   - teacher can upload an .xlsx workbook for one teacher workspace
   - import uses existing workbook_import logic
   - validation/import errors are shown clearly

5. Response quality:
   - success response should include a short import/export summary where practical
   - do not expose low-level stack traces to user

Constraints:
- no FSM
- no broad workspace UI
- no Google Sheets API
- no web admin panel
- no new content versioning
- keep handlers thin
- business logic must remain outside Telegram layer

Architecture expectations:
- add focused Telegram handler module(s) if needed
- reuse existing workbook_export/workbook_import modules
- do not turn teacher_handlers.py into a catch-all file

Testing requirements:
- tests for permission checks
- tests for explicit workspace scoping
- tests for export handler behavior
- tests for import handler behavior
- tests for clear failure on student workspace target
- keep business logic tests outside Telegram runtime where possible

Documentation:
- update CHANGELOG.md
- update context/current_state.md
- update help text if needed

Workflow:
1. architect
2. complexity_guard
3. coder
4. complexity_guard

Definition of done:
- teacher can export a workbook from a teacher workspace through Telegram
- teacher can import a workbook into a teacher workspace through Telegram
- handlers stay thin
- permissions are enforced
- errors are clear
- tests pass
- docs updated