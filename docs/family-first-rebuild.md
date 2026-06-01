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
- homework still needs its own migration slice because the legacy training session model stores `assignment_id` against the old homework table.

Wave 3:
- delete legacy entry points and modules that only exist for workspace and publish flows

## First implementation slice
The first coder task should deliver:
- minimal SQLite schema for the family-first model
- family membership reads and writes
- family-owned topics and learning-item lookup
- personal progress and homework tables
- focused tests for the new persistence layer

This slice should not try to preserve legacy compatibility.
