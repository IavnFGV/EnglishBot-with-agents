# Family-First Rebuild

## Decision
- Rebuild EnglishBot in the current repository.
- Keep the existing deploy path.
- Do not preserve the legacy teacher/student workspace architecture as the foundation of the new product.
- Remove legacy flows aggressively when they block a simpler family-first model.

## Product core
The new bot should support only:
- shared family dictionary
- shared family topics
- personal progress
- personal homework

Anything outside that scope is legacy or follow-up work.

## Target data model
- `users`
- `families`
- `family_members`
- `learning_items`
- `topics`
- `topic_items`
- `user_progress`
- `homework_assignments`
- `homework_assignment_items`

Rules:
- `learning_items` and `topics` belong to a family, not a workspace.
- `user_progress` belongs to one user.
- homework is personal, but created within one family.
- SQLite stays the runtime source of truth.

## Main user flows
1. First run: create a family or enter the existing family setup.
2. Open the family dictionary.
3. Open family topics and start learning from a topic.
4. Run `/learn` from personal progress.
5. Open personal homework and resume or finish it.
6. Assign homework to a family member.

## Reuse
Keep and reuse where it stays simple:
- `training.py` and the exercise engine
- homework and training Telegram UX patterns
- `aiogram-dialog` for multi-step flows
- single-message compact navigation
- `i18n.py`
- command registry wiring

## Remove
Treat these as removal targets, not architectural constraints:
- teacher/student workspaces
- publish flow
- invite/join as the base model
- topic grants
- admin facade
- teacher-role-centered access design
- workspace-based runtime ownership

## First cut plan
Wave 1:
- freeze legacy architecture as old behavior
- add the family-first schema
- add family membership and family-owned content lookup
- add personal progress and homework persistence on the new schema

Wave 2:
- connect `/learn`, topics, and homework to the new family-first data model
- build compact family-first navigation

Current status:
- `/learn` is already connected to family-owned learning items when the user belongs to a family.
- learner homework is now family-first only on the active runtime path.
- family homework uses its own `family_homework_assignment_id` in `training_sessions`.
- the focused learner-homework UI tests now launch family homework directly, which reduces the remaining invite/join dependency to older workspace-first domain coverage instead of active learner UX coverage.
- the homework-specific `training_handlers` coverage now also runs on family homework directly, so the remaining invite/join dependency is shrinking toward older domain tests instead of active learner runtime coverage.
- `/topics` is now family-first only on the active runtime path, without topic grants or published student-workspace copies.
- the focused `/topics` Telegram handler coverage now also runs on family topics directly, so invite/join is no longer part of the active topic-picker UI coverage.
- the old `teacher_student.py` invite helper, `simple_mode.py`, and their dedicated tests are gone; the remaining legacy surface is now workspace-first persistence, not onboarding or bootstrap scaffolding.
- `/teacher_content` and `/create_assignment` are now family-first on the active runtime path: family members work against one shared family content surface, and non-family users no longer enter those authoring flows.
- the assignment-dialog confirm snapshot now understands virtual family workspaces correctly, so the main topic/words/recipient/confirm authoring path can be covered on family content directly.
- the main bot command list is now trimmed to family-first commands only.
- legacy admin, invite/join, assign/grant, and workbook Telegram handlers have been removed from active runtime wiring and deleted from the codebase.

Wave 3:
- delete the remaining workbook and workspace-helper leftovers once the team decides whether workbook tooling stays as an offline maintenance path

## First implementation slice
The first coder task should deliver:
- minimal SQLite schema for the family-first model
- family membership reads and writes
- family-owned topics and learning-item lookup
- personal progress and homework tables
- focused tests for the new persistence layer

This slice should not try to preserve legacy compatibility.
