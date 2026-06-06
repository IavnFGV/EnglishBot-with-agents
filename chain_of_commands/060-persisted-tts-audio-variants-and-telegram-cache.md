Сделай в текущем репозитории EnglishBot следующий TTS storage slice после базовой live-интеграции: добавь persistent synthesized-audio variants для `learning_item`, чтобы бот мог хранить несколько локальных TTS озвучек одного и того же учебного элемента для разных голосов и/или моделей, а поверх этого использовать отдельный Telegram `file_id` cache как transport-only layer.


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
* chain_of_commands/058-internal-tts-service-integration.md

Контекст:

- предыдущая TTS итерация уже должна была дать:
  - optional internal TTS client
  - `Listen` action в learner runtime
  - persisted user-selected `voice_id`
  - fail-closed live TTS request path
- теперь нужно перейти от purely live synthesis к управляемому persistent storage слою для TTS audio variants
- в репозитории уже есть важный принцип:
  - runtime truth должна быть локальной и понятной
  - Telegram `file_id` не является source of truth
  - transport cache должен оставаться отдельным от core domain data
- в проекте уже есть asset registry и отдельный Telegram media cache direction
- новая задача не должна превращать synthesized audio в случайную временную кучу файлов без модели владения

Работай строго по правилам репозитория из `AGENTS.md`:

- не расширяй scope на старые workspace/publish surfaces
- читай только task-specific файлы по `docs/module-map.md`
- все bot-facing тексты только через `englishbot/i18n.py`
- optional extras must not become required for core runtime
- новые или измененные команды проходят через `englishbot/command_registry.py`
- после завершения обнови `CHANGELOG.md`, `context/current-state.md` и `.env.example`, если появятся env changes
- держи `context/current-state.md` коротким

Перед реализацией подними только нужный контекст:

- asset / persistence slice:
  - `englishbot/assets.py`
  - `englishbot/db.py`
  - `englishbot/training.py`, only if `learning_item` resolution helpers matter
  - `englishbot/training_handlers.py`, only if runtime send path changes
- TTS integration slice:
  - the TTS client module introduced by the previous iteration
  - any voice preference helper introduced by the previous iteration
- focused tests:
  - `tests/test_training_handlers.py`
  - `tests/test_training.py`, only if domain resolution changes
  - asset/media-cache focused tests already closest to this area
  - new focused persistence tests for the synthesized-audio model

Главная цель:

- хранить локальные synthesized audio variants осмысленно и предсказуемо
- позволить одному `learning_item` иметь несколько озвучек
- различать варианты не только по слову, но и по voice/model identity
- не смешивать runtime audio truth с Telegram transport cache

Ключевая идея модели:

- один `learning_item` может иметь несколько synthesized audio variants
- варианты должны различаться как минимум по:
  - `learning_item_id`
  - `voice_id`
  - engine/model identity
- если модель TTS изменилась, старый audio variant не должен тихо считаться актуальным только потому, что `voice_id` совпал

Ожидаемая identity shape:

- минимально:
  - `learning_item_id`
  - `voice_id`
  - `tts_model_key` или `tts_engine_key`
- желательно также иметь:
  - `source_text`
  - или более компактно `source_text_hash`
- выбери минимальную форму, которую легко держать в голове, но которая fail-closed при изменении текста или движка

1. Separate persistent TTS variant layer

- не добавляй просто одно поле `audio_asset_id` в `learning_items` и не считай задачу закрытой
- нужен слой, который умеет хранить несколько вариантов одной озвучки
- выбери минимальную SQLite модель:
  - либо отдельная таблица synthesized variants, которая ссылается на `asset_id`
  - либо другой такой же понятный вариант
- но структура должна явно выражать:
  - какой `learning_item`
  - какой `voice_id`
  - какая model/engine identity
  - какой локальный asset/file является runtime truth для этого варианта

2. Asset truth and filenames

- synthesized audio file должен храниться локально на диске как runtime truth
- Telegram `file_id` не заменяет локальный файл
- имена файлов должны быть понятными и стабильными
- избегай временно-случайного naming как permanent contract
- допустимы короткие deterministic names на базе persisted ids или variant ids
- storage layout выбери в существующем repo стиле рядом с другими runtime media

3. Transport cache stays separate

- поверх persistent audio variant можно и нужно использовать отдельный Telegram cache
- но этот cache остается transport-only
- если есть общий media cache helper для `audio` / `voice`, reuse его
- если нет, расширяй существующий transport cache локально и без redesign
- Telegram cache identity должна ссылаться на runtime asset/variant cleanly, but not replace it

4. Cache key expectations

- на domain/storage уровне variant identity должна различать:
  - `learning_item`
  - `voice_id`
  - model/engine key
- это по смыслу и есть составной ключ варианта
- если реализуешь SQL uniqueness, сделай его fail-closed и явным
- не допускай, чтобы одна и та же запись бесконтрольно переиспользовалась после смены текста или модели

5. Invalidation rules

- продумай простой и явный invalidation rule
- случаи, которые нельзя игнорировать:
  - изменился English text у `learning_item`
  - изменился `voice_id`
  - изменился TTS engine/model key
- ожидание:
  - старый variant не должен silently считаться свежим
  - лучше получить miss и пересинтезировать, чем сыграть устаревший звук
- не превращай это в сложный lifecycle manager с фоновым GC, если это не нужно для минимального reliable behavior

6. Generation policy

- выбери минимальный практический policy:
  - generate on demand on first listen for this exact variant identity
  - persist local file
  - subsequent listens reuse local file and then Telegram cache if available
- не делай eager generation для всех items/voices
- не делай batch precompute jobs в этой итерации

7. Runtime behavior

- при `Listen` flow:
  - resolve current `learning_item`
  - resolve effective `voice_id`
  - resolve current model/engine key
  - lookup existing persistent audio variant
  - if hit: send existing local file or cached Telegram id
  - if miss: call TTS, persist local asset/variant, then send it
- flow должен оставаться fail-closed:
  - если генерация не удалась, learner session не ломается
  - если Telegram cache устарел, fallback на локальный файл

8. Scope discipline

Минимальный практический scope этой итерации:

- persistent TTS audio variant data model
- local file persistence with clear filenames
- composed variant identity keyed by `learning_item` + `voice_id` + model/engine key
- reuse/extend Telegram cache for `voice` or `audio`
- on-demand generate-and-store flow from learner `Listen`
- focused tests

Не делай в этой итерации:

- waveform editing or normalization framework
- multiple TTS providers abstraction layer unless current code already needs it
- admin UI for bulk regeneration
- batch backfill for all existing items
- teacher-side TTS asset curation UI
- large asset-lifecycle cleanup unrelated to synthesized audio

9. Tests

Добавь focused tests минимум для:

- first listen for a `learning_item` + `voice_id` + model key miss synthesizes and persists a local variant
- second listen for the same composed identity reuses the persisted variant without re-synthesizing
- same `learning_item` with different `voice_id` creates a distinct persisted variant
- same `learning_item` with same `voice_id` but different model/engine key creates a distinct persisted variant
- changed source English text invalidates old variant identity or causes a safe miss
- Telegram cached `file_id` for a persisted audio variant is transport-only and falls back to local file when stale
- persistent variant layer remains separate from the core `learning_items` row and separate from Telegram cache rows

10. Documentation updates

Обнови:

- `CHANGELOG.md`
- `context/current-state.md`
- `docs/architecture.md`, only if structural boundaries changed materially
- `.env.example`, if env vars were added

Current state should clearly say:

- `learning_item` can now own multiple persistent synthesized audio variants
- variant identity distinguishes at least `voice_id` and TTS model/engine identity
- local synthesized audio files are the runtime source of truth
- Telegram `file_id` remains only a cache layer above those persisted variants

Ожидаемый итог:

- для одного `learning_item` можно безопасно хранить несколько TTS озвучек
- composed identity не дает тихо смешать разные voices/models
- локальный audio asset становится понятной runtime truth
- Telegram reuse остается отдельным transport cache layer
- первая live TTS интеграция получает естественное продолжение без asset-model chaos
