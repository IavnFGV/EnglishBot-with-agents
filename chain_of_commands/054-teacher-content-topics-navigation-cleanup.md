Сделай в текущем репозитории EnglishBot узкий cleanup topics navigation для family-first `/teacher_content`, чтобы экран выбора темы стал понятным и telegram-first, без дублирующего списка и без странного pager вида `1 < 1 > 1`.


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

- активный `/teacher_content` уже family-first
- проблема сейчас именно в topics screen внутри `teacher_content_dialog`
- на экране одновременно показываются:
  - текстовый список тем внутри `screen_text`
  - тот же список как inline buttons
  - встроенный pager `ScrollingGroup`, который выглядит как `1 < 1 > 1`
  - отдельный ручной `Prev/Next`
- в результате экран визуально перегружен, а пользователь не понимает, чем пользоваться

Работай строго по правилам репозитория из `AGENTS.md`:

- не расширяй scope на старые workspace/publish flows
- читай только task-specific файлы по `docs/module-map.md`
- все bot-facing тексты только через `englishbot/i18n.py`
- новые или измененные команды обязательно проходят через `englishbot/command_registry.py`
- после завершения обнови `CHANGELOG.md`, `context/current-state.md` и `.env.example`, если появятся env changes
- держи `context/current-state.md` коротким

Перед реализацией подними только нужный контекст:

- `englishbot/teacher_content_dialog.py`
- `englishbot/teacher_content.py`
- focused tests:
  - `tests/test_teacher_content_handlers.py`
- если понадобится строковый ключ:
  - `englishbot/i18n.py`

Главная цель:

- topics screen в `/teacher_content` должен использовать один понятный navigation model
- убрать визуальное нагромождение и непонятный widget pager

Важно:

- это не задача про browser screen topic items
- это не задача про teacher content image/media editor
- это не задача про bulk edit logic
- это не задача про family data model
- это topics list navigation cleanup only

Целевое поведение:

1. One list representation

- topics screen не должен показывать один и тот же список дважды
- если темы выбираются кнопками:
  - не дублируй их текстом внутри `screen_text`
- `screen_text` должен остаться компактным:
  - family name
  - короткий prompt
  - page/position summary

2. One pagination model

- на экране должен остаться только один pagination mechanism
- не должно быть одновременно:
  - `ScrollingGroup` pager
  - и отдельного ручного `Prev/Next`
- убери непонятный control вида `1 < 1 > 1`

3. Human-readable pagination

- пользователь должен понимать, где он находится в списке
- допустимы варианты типа:
  - `Page 1/3 · total 22`
  - `Showing 1-8 of 22`
- если кнопка `Next` ведет вперед:
  - состояние страницы должно обновляться предсказуемо
- если тем меньше одной страницы:
  - лишние controls не показывай

4. Keep Telegram-first compactness

- один logical screen
- не спамить новыми сообщениями
- selection topic -> browser должен остаться рабочим
- `Create`, `Bulk edit`, `Cancel` должны остаться понятными и на месте, если нет сильной причины их двигать

5. Minimal architecture change

- не переписывай весь dialog
- используй самый маленький cleanup
- если у тебя уже есть manual pagination через `_slice_page()` и `_clamp_list_page()`:
  - не добавляй еще один параллельный navigation layer

6. Tests

Добавь focused tests минимум для:

- topics screen больше не дублирует список тем в `screen_text`
- topics screen больше не использует confusing `ScrollingGroup` pager behavior
- `Next` page реально показывает следующий page slice
- `Prev` page реально возвращает предыдущий page slice
- topic selection со второй страницы продолжает открывать browser screen корректно
- empty/single-page behavior остается аккуратным

7. Documentation updates

Обнови:

- `CHANGELOG.md`
- `context/current-state.md`
- `docs/architecture.md`, only if structural boundaries changed materially

Current state should clearly say:

- `/teacher_content` topics screen now uses one compact pagination model
- duplicated topic rendering and the confusing extra pager were removed

8. Non-goals

- не менять topic browser item navigation
- не менять teacher content edit prompts
- не менять family authoring permissions
- не менять bulk edit command behavior
- не делать большой redesign teacher UI beyond topics navigation cleanup

Ожидаемый итог:

- экран выбора темы в `/teacher_content` станет понятным с первого взгляда
- пользователь увидит один список, один pager и понятный page summary
- исчезнет странный `1 < 1 > 1`
- поведение останется компактным и telegram-first
