Сделай в текущем репозитории EnglishBot следующую итерацию learner flow polish для family-first training UI: показывай learning item image в вопросе там, где картинка уже есть в runtime data, но сейчас не рендерится в Telegram learner flow.


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

- активный learner flow уже family-first
- `training.py` уже прокидывает `image_ref` в question payload
- `ResolvedLearningItem` уже умеет брать `PRIMARY_IMAGE_ROLE` из asset registry
- но `training_handlers.py` сейчас рендерит learner question как text-only message
- в результате `/learn` и другие training entrypoints не показывают картинку learning item, даже когда она есть

Работай строго по правилам репозитория из `AGENTS.md`:

- не расширяй scope на старые workspace/publish flows
- читай только task-specific файлы по `docs/module-map.md`
- все bot-facing тексты только через `englishbot/i18n.py`
- новые или измененные команды обязательно проходят через `englishbot/command_registry.py`
- после завершения обнови `CHANGELOG.md`, `context/current-state.md` и `.env.example`, если появятся env changes
- держи `context/current-state.md` коротким

Перед реализацией подними только нужный контекст:

- `englishbot/training.py`
- `englishbot/training_handlers.py`
- `englishbot/exercises.py`
- focused training tests:
  - `tests/test_training.py`
  - `tests/test_training_handlers.py`
- если для image fallback понадобится точный helper:
  - `englishbot/assets.py`

Главная цель:

- learner question card должна показывать image, если у текущего learning item есть usable `image_ref`
- если картинки нет или она недоступна, learner flow должен безопасно откатиться к текущему text-only behavior

Важно:

- это не задача про homework progress image
- это не задача про teacher content UI
- это не задача про asset migration
- это learner training message rendering task

Целевое поведение:

1. Where images should appear

- `/learn` должен показывать картинку для current learning item, если она есть
- тот же behavior должен работать и для других entrypoints, которые используют тот же training engine/question renderer:
  - topic-based launches
  - homework launches
- shared training engine должен оставаться shared; не делай отдельные параллельные question renderers без необходимости

2. Message model

- соблюдай Telegram UI rules из `AGENTS.md`
- не превращай flow в message spam
- вопрос должен оставаться одним logical screen
- если сейчас progress и question разделены на два сообщения, не ломай это без нужды
- image question card должна переиспользоваться и обновляться по возможности, а не плодить новые сообщения на каждый шаг

3. Rendering behavior

- если у question есть usable `image_ref`:
  - learner должен видеть image + question text + inline keyboard
- если usable image нет:
  - current text-only rendering должен остаться
- easy / medium / hard stages должны продолжать работать одинаково с точки зрения exercise logic; меняется только UI rendering

4. Asset source of truth

- source of truth по-прежнему asset registry через `image_ref`
- не добавляй новых media columns
- не делай обходной runtime source вне SQLite
- поддержи текущий family-first asset model как есть

5. Fallback and failure behavior

- если local image file missing
- если `image_ref` указывает на невалидный путь
- если Telegram rejects photo/media edit
- если question screen уже text-only и image не удалось показать

Ожидание:

- learner flow не должен падать
- training session не должна ломаться
- bot должен fail closed в сторону text-only question, а не exception

6. Editing strategy

- продумай, как question screen будет обновляться между шагами:
  - image -> image
  - image -> no image
  - no image -> image
  - no image -> no image
- текущий learner flow уже хранит `current_question_message_id`
- используй существующую архитектуру осознанно, а не добавляй новый хаотичный state layer

7. UX constraints

- keyboard options должны остаться такими же для easy / medium / hard
- feedback (`Correct.`, etc.) должен продолжать отображаться корректно
- не теряй текущую логику summary/progress cleanup
- existing homework progress image behavior должен остаться как есть

8. Tests

Добавь focused tests минимум для:

- question with image renders photo-based learner card
- question without image stays text-only
- transition image -> image reuses or updates message correctly
- transition no-image -> image works correctly
- transition image -> no-image works correctly
- invalid or missing image falls back to text-only question without breaking session
- easy / medium / hard keyboards still render correctly with image-based question cards
- homework progress image behavior is not regressed

9. Documentation updates

Обнови:

- `CHANGELOG.md`
- `context/current-state.md`
- `docs/architecture.md`, only if structural boundaries changed materially

Current state should clearly say:

- learner training question cards now show linked learning item images when available
- learner flow falls back to text-only questions when an image cannot be shown
- homework progress image remains a separate UI element from the question card

10. Non-goals

- не менять exercise generation rules
- не переписывать training engine
- не трогать workbook import/export
- не делать webapp
- не добавлять AI/TTS
- не менять teacher content editing UX в этой итерации
- не делать массовый redesign learner flow beyond the image question card behavior

Ожидаемый итог:

- learner flow наконец показывает картинки там, где данные уже есть
- UI остается компактным и telegram-first
- question rendering не ломается на переходах между image и text-only items
- семейная training runtime model остается простой и локальной
