Сделай в текущем репозитории EnglishBot узкий family-first UX slice: добавь явную пользовательскую команду `/homework`, чтобы ученик мог открыть свою домашку напрямую, не заходя каждый раз через `/start`.


Use the agent workflow for this task.

Execution order:

1. architect
2. complexity_guard
3. coder

Read first:

* AGENTS.md
* docs/module-map.md
* docs/architecture.md
* context/current-state.md

Контекст:

- сейчас learner homework runtime уже существует:
  - assignment creation идет через `/create_assignment`
  - learner homework UI уже существует через `homework_dialog` / `homework_handlers`
  - training runtime для homework уже family-first
- но явной команды `/homework` в активном command set сейчас нет
- фактически learner попадает в homework-first путь через `/start`, если есть активные assignments
- это неудобно:
  - пользователь не видит очевидную точку входа в домашку
  - для возврата в homework приходится помнить про `/start`
  - command menu не отражает уже существующий важный learner flow

Работай строго по правилам репозитория из `AGENTS.md`:

- не расширяй scope на старые workspace/publish flows
- читай только task-specific файлы по `docs/module-map.md`
- все bot-facing тексты только через `englishbot/i18n.py`
- новые или измененные команды обязательно проходят через `englishbot/command_registry.py`
- после завершения обнови `CHANGELOG.md`, `context/current-state.md` и `.env.example`, если появятся env changes
- держи `context/current-state.md` коротким

Перед реализацией подними только нужный контекст:

- `englishbot/command_registry.py`
- `englishbot/bot.py`
- `englishbot/homework_handlers.py`
- `englishbot/homework_dialog.py`
- `englishbot/i18n.py`
- focused tests:
  - `tests/test_command_registry.py`
  - `tests/test_bot.py`
  - `tests/test_homework_handlers.py`
  - `tests/test_homework_dialog.py`, only if entrypoint behavior is asserted there

Главная цель:

- дать learner-у отдельную явную команду `/homework`
- не создавать новый homework runtime path
- не дублировать бизнес-логику homework list/start/resume
- просто открыть уже существующий family-first homework flow через новую discoverable command entrypoint

Целевое поведение:

1. New explicit command

- добавить `/homework` в `englishbot/command_registry.py`
- команда должна появляться в активном command menu
- текст описания команды должен идти через `englishbot/i18n.py`

2. Reuse existing homework flow

- `/homework` не должен открывать какую-то вторую реализацию
- он должен переиспользовать уже существующий learner homework UI / dialog entrypoint
- если уже есть helper для входа в homework flow, используй его
- если нет, добавь минимальный thin entry helper без переноса бизнес-логики в handler

3. Family-first behavior only

- новая команда работает только на активном family-first runtime path
- не надо оживлять старые assignment/workspace surfaces
- если у пользователя нет активной homework, поведение должно быть понятным и согласованным с текущим learner UX

4. UX expectations

- learner должен иметь прямой способ:
  - открыть список своей homework
  - вернуться к homework после паузы
  - не использовать `/start` как единственную навигационную точку
- `/start` homework-first behavior можно сохранить, но `/homework` должен стать явной альтернативой, а не обходным путем

5. Tests

Добавь focused tests минимум для:

- `/homework` зарегистрирован в command registry
- `/homework` появляется в active command set / bot command configuration
- `/homework` открывает existing learner homework flow
- если у learner нет homework, команда отвечает корректно и не падает

6. Documentation updates

Обнови:

- `CHANGELOG.md`
- `context/current-state.md`
- `docs/architecture.md`, only if structural boundaries changed materially

Current state should clearly say:

- learner homework is now reachable both from `/start` and from explicit `/homework`
- homework runtime path remains the same family-first flow

7. Non-goals

- не redesign'ить learner homework UI
- не добавлять новый homework persistence layer
- не менять assignment semantics
- не добавлять deep links
- не переписывать `/start` заново
- не заводить вторую homework command path с отдельной логикой

Ожидаемый итог:

- в боте появляется явная команда `/homework`
- команда просто открывает уже существующий learner homework flow
- UX становится понятнее без архитектурного дублирования

Homework mechanic note to preserve during future changes:

- Family homework uses a per-assignment boost layer on top of the normal per-word staged flow.
- Current intended homework assumption:
  - one word normally needs `3 easy` correct answers, then `2 medium` correct answers
  - after that normal per-word flow, the word counts as completed for homework even without a mandatory normal hard step
- Separate boost rule:
  - after `4` correct answers in a row across the active homework assignment, the learner enters boosted `hard` mode
  - in boosted mode, the current word can be finished immediately by one correct typed hard answer
  - when a boosted hard answer is correct, that word is marked completed and the boost continues to the next word
  - if the boosted word is the last unfinished word, the homework completes
- Skip-hard rule in homework:
  - `Skip hard` is not treated as a mistake
  - `Skip hard` clears the boost and shows the same word again at the stage it should normally be on in the per-word flow
  - `Skip hard` must not auto-complete that word unless the normal per-word flow had already completed it
- Do not silently replace this with a simpler “always finish on hard” or “global hard after four correct means hard-only forever” model.
