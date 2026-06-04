Сделай в текущем репозитории EnglishBot узкий, но устойчивый caching layer для Telegram media delivery: добавь отдельную persistence-таблицу для Telegram `file_id`, чтобы бот мог переиспользовать уже загруженные в Telegram image/audio/voice assets без повторной отправки бинарника, но при этом не смешивать этот кеш со смысловой data model обучающей системы.


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

- сейчас активный runtime хранит asset truth локально:
  - `assets.local_path` = runtime source of truth
  - `assets.source_url` = optional traceability only
- learner question images сейчас отправляются в Telegram как локальный файл через `FSInputFile`
- teacher-content image preview сейчас идет через `aiogram-dialog` media path
- homework progress image тоже уходит как новый файл, но это отдельный динамический случай
- для статичных learning-item media это неидеально:
  - Telegram каждый раз получает повторную загрузку того же файла
  - бот тратит лишний upload/network budget
  - UX может быть медленнее, чем при повторном использовании `file_id`
- при этом не хочется тащить Telegram transport details в core learning model
- следующим шагом планируется TTS/service-generated media, и тот же caching layer должен уметь хранить Telegram `file_id` не только для images, но и для audio/voice assets тоже
- важно не получить две независимые cache-реализации:
  - одну для direct `aiogram` send/edit path
  - другую для `aiogram-dialog`

Работай строго по правилам репозитория из `AGENTS.md`:

- не расширяй scope на старые workspace/publish flows
- читай только task-specific файлы по `docs/module-map.md`
- все bot-facing тексты только через `englishbot/i18n.py`
- новые или измененные команды обязательно проходят через `englishbot/command_registry.py`
- после завершения обнови `CHANGELOG.md`, `context/current-state.md` и `.env.example`, если появятся env changes
- держи `context/current-state.md` коротким

Перед реализацией подними только нужный контекст:

- `englishbot/assets.py`
- `englishbot/training_handlers.py`
- `englishbot/teacher_content.py`, only if asset send/edit flow touches it
- `englishbot/teacher_content_dialog.py`, if `aiogram-dialog` media path needs integration
- `englishbot/db.py`
- bot/dialog wiring only if needed for one shared Telegram media cache backend
- focused tests:
  - `tests/test_training_handlers.py`
  - `tests/test_teacher_content_handlers.py`, if dialog media path becomes part of the shared cache
  - other focused asset/handler tests only if directly relevant

Главная цель:

- ввести отдельный кеширующий persistence layer для Telegram `file_id`
- не делать этот слой частью обучающей предметной модели
- позволить любому asset иметь transport-level cached Telegram ids
- сразу спроектировать слой так, чтобы он годился для image, audio и voice media
- сделать слой совместимым и с direct `aiogram` send/edit code, и с `aiogram-dialog` `media_id_storage`

Важно:

- это не задача про redesign asset registry
- это не задача про замену `local_path` как runtime source of truth
- это не задача про массовую миграцию existing assets
- это не задача про перевод runtime на URL-based media
- это не задача про cache warming всех ассетов заранее
- это не задача про homework progress image, если только это не получается почти бесплатно и безопасно

Целевое поведение:

1. Separate cache table, not domain-table pollution

- нужен отдельный SQLite table для Telegram media cache
- эта таблица должна быть концептуально transport/cache layer, а не частью main learning schema
- не добавляй Telegram-specific `file_id` columns в `assets`
- не смешивай кеш с `learning_items`, `topics`, homework или workbook-import model

Ожидаемая форма слоя:

- привязка к `asset_id`
- тип Telegram media transport representation
- cached `file_id`
- optional metadata needed for cache validity / debugging

Например по смыслу:

- `asset_id`
- `telegram_media_kind` (`photo`, `audio`, `voice`)
- `telegram_file_id`
- optional timestamps

Но выбери минимальную форму, которую легко держать в голове.

2. Cache semantics

- `local_path` остается source of truth
- Telegram `file_id` это лишь ускоряющий cache
- при наличии валидного cached `file_id` бот должен предпочитать его повторной отправке бинарника
- если кеша нет, бот должен отправить локальный файл обычным способом
- после успешной отправки нужно сохранить `file_id` для будущего reuse

3. Fail-closed transport behavior

- если cached `file_id` больше не работает
- если Telegram rejects cached media
- если кеш поврежден
- если asset row удален или заменен

Ожидание:

- бот должен fallback'нуться на локальный файл
- после успешного fallback upload кеш должен уметь self-heal новым `file_id`
- learner flow не должен падать из-за Telegram cache mismatch
- dialog-based teacher preview тоже не должен терять экран только из-за stale cache

4. Asset replacement / invalidation

- продумай, как cache будет инвалидироваться, когда asset physically changes
- не полагайся на то, что один и тот же `asset_id` всегда гарантирует тот же самый binary forever
- если existing code уже делает replace через новый asset row, используй это как упрощающий фактор
- если нужен минимальный invalidation rule, сделай его максимально простым и явным

Цель:

- не держать stale `file_id` бесконтрольно
- но и не превращать задачу в asset lifecycle manager

5. Media kinds for future TTS

- текущая реализация может начать с image path в learner flow
- но схема и helper API должны быть явно пригодны также для:
  - `audio`
  - `voice`
- следующая TTS/media iteration должна мочь положить туда cached Telegram ids без redesign этой таблицы

6. Scope priority

Минимальный практический scope этой итерации:

- table + helpers
- use cache for static learner question images
- save/reuse `photo` `file_id`
- prepare API surface so future audio/voice flows can plug in cleanly
- ensure the same persistent cache backend can also be used by `aiogram-dialog` media rendering via `media_id_storage`

Если audio/voice reuse получается безопасно и локально в той же итерации, можно включить, но не ценою расползания scope.

7. Where not to overreach

- не внедряй Telegram transport cache во все send paths подряд
- не трогай bulk-edit import/export
- не делай общий media abstraction framework ради одной фичи
- не заводи network dependence on remote URLs
- не делай background refresh job
- не переписывай весь learner runtime на `aiogram-dialog` и не переписывай teacher flows обратно в direct handlers

8. Tests

Добавь focused tests минимум для:

- first image send without cache uploads local file and stores returned Telegram `file_id`
- second send for the same asset prefers cached `file_id` over `FSInputFile`
- invalid cached `file_id` falls back to local file instead of breaking learner flow
- successful fallback after invalid cache refreshes stored `file_id`
- cache persistence layer is asset-linked but separate from the main `assets` table
- helper API can represent future `photo` / `audio` / `voice` kinds cleanly even if only `photo` is actively used in this slice
- if dialog media path is hooked up, add one focused test proving `aiogram-dialog` storage writes/reads the same project cache table instead of an isolated in-memory-only cache

9. Documentation updates

Обнови:

- `CHANGELOG.md`
- `context/current-state.md`
- `docs/architecture.md`, only if structural boundaries changed materially

Current state should clearly say:

- runtime media source of truth is still local file storage
- Telegram `file_id` is now a separate cache layer, not part of core asset truth
- the cache is designed to support future image/audio/voice reuse, including upcoming TTS-backed media
- `aiogram-dialog` media path should not drift onto a separate cache implementation if the repo still uses dialogs

10. Non-goals

- не превращать Telegram cache в mandatory storage dependency
- не удалять local file runtime path
- не переводить asset truth на Telegram storage
- не делать eager cache fill for all assets
- не чинить все historical media send paths in one sweep
- не redesign'ить всю teacher-content или homework media delivery architecture

Ожидаемый итог:

- бот получает аккуратный Telegram transport cache layer
- основной asset model остается чистой и локально-ориентированной
- learner image delivery становится дешевле и быстрее на повторных показах
- dialog-based static previews могут пользоваться тем же persistent cache backend без отдельного in-memory-only fork
- будущий TTS/media step сможет использовать тот же слой для `audio` и `voice` без нового schema redesign
