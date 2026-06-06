Сделай в текущем репозитории EnglishBot узкий, но устойчивый family-first TTS integration slice: подключи отдельный internal-only TTS service для озвучивания английского текста в learner runtime, начав с минимального рабочего варианта `Listen + voice selection`, без превращения TTS в обязательную зависимость core bot runtime.


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

- EnglishBot уже family-first и Telegram-first
- learner runtime уже существует в `training.py` / `training_handlers.py`
- есть два ключевых learner quiz surfaces:
  - quiz с выбором варианта ответа
  - quiz с ручным вводом английского слова
- в проекте уже есть отдельный Telegram transport cache layer для media reuse:
  - локальный runtime file остается source of truth
  - Telegram `file_id` остается только cache layer
  - schema/helper shape уже готова для `photo`, `audio`, `voice`
- отдельный TTS service уже существует вне этого репозитория
- он internal-only, без публичного домена, и должен дергаться ботом по internal hostname внутри docker network
- TTS service не должен тянуть в себя доменную логику EnglishBot
- future persistent synthesized-audio storage is expected later, but this first iteration must stay live-request-first and must not redesign the asset model yet

Внешний TTS API, под который нужно подстроиться:

- `GET /healthz`
  - response: `{ "status": "ok" }`
- `GET /voices`
  - response:
    - `default_voice_id`
    - `voices: [{ "id": "...", "label": "..." }]`
- `POST /v1/synthesize`
  - request:
    - `{ "text": "apple", "voice_id": "en_US_lessac" }`
  - success:
    - `200 OK`
    - `Content-Type: audio/ogg`
    - raw audio bytes in body
  - validation error:
    - `400` with compact JSON error
  - server error:
    - `500`

Предполагаемый internal base URL:

- `http://tts-service:8000`

Пример desired voice mapping для user-facing UI:

- `en_US_amy` -> `Amy` / `Female, US`
- `en_US_lessac` -> `Emma` / `Female, US`
- `en_US_ryan` -> `Ryan` / `Male, US`
- `en_GB_alba` -> `Alice` / `Female, UK`
- `en_GB_alan` -> `Alan` / `Male, UK`

Работай строго по правилам репозитория из `AGENTS.md`:

- не расширяй scope на старые workspace/publish surfaces
- читай только task-specific файлы по `docs/module-map.md`
- все bot-facing тексты только через `englishbot/i18n.py`
- optional AI/TTS/WebApp extras must not become required for core runtime
- новые или измененные Telegram commands проходят через `englishbot/command_registry.py`
- после завершения обнови `CHANGELOG.md`, `context/current-state.md` и `.env.example`, если появятся env changes
- держи `context/current-state.md` коротким

Перед реализацией подними только нужный контекст:

- learner/training slice:
  - `englishbot/training.py`
  - `englishbot/training_handlers.py`
  - `englishbot/exercises.py`, only if answer-card state depends on exercise type
- user settings / persistence slice:
  - `englishbot/user_profiles.py`
  - `englishbot/i18n.py`
  - `englishbot/db.py`
- startup/config slice:
  - `englishbot/config.py`
  - `englishbot/bootstrap.py`, only if wiring/config bootstrap changes are needed
  - `englishbot/runtime.py` or `englishbot/bot.py`, only if dependency wiring needs a minimal hook
- focused tests:
  - `tests/test_training.py`
  - `tests/test_training_handlers.py`
  - `tests/test_user_profiles.py`
  - `tests/test_i18n.py`
  - `tests/test_bootstrap.py`, only if startup/config behavior changes

Главная цель:

- добавить минимальный полезный TTS UX в learner runtime
- дать пользователю кнопку `Listen`
- дать пользователю выбор голоса
- сохранить выбранный `voice_id` между сессиями
- при неработающем или не настроенном TTS бот не должен падать и не должен ломать quiz flow

Приоритет этой итерации:

1. минимальный рабочий TTS path для английского текста
2. выбор и сохранение user voice preference
3. мягкий fail-closed behavior
4. reuse существующих learner UI/state patterns
5. подготовить API shape так, чтобы будущий audio/voice Telegram reuse слой подключался cleanly

Что именно нужно реализовать:

1. Minimal architecture

- добавь узкий client module для internal TTS service
- client должен уметь:
  - health check helper, only if он почти бесплатен и нужен текущему wiring
  - fetch voices
  - synthesize text with `voice_id`
- не тащи business logic EnglishBot внутрь TTS client
- TTS client должен принимать только то, что знает внешний сервис:
  - `text`
  - `voice_id`
- network behavior должен быть компактным:
  - небольшой timeout
  - понятные typed exceptions или аккуратный result layer
  - distinction между validation / unavailable / unexpected failure на уровне helper API, если это помогает не расползтись handler logic

2. Optional runtime integration only

- TTS integration must stay optional
- если TTS base URL не настроен, core bot runtime все равно стартует и работает
- отсутствие TTS не должно ломать `/learn`, homework, `/topics`, `/start`, `/help`, `/teacher_content` и прочие core flows
- если integration выключена конфигом:
  - просто не показывай TTS-specific controls
  - или показывай их только там, где graceful fallback уже гарантирован
- не добавляй hard dependency на внешний TTS service во время startup bootstrap

3. User voice preference persistence

- выбери минимальное место хранения выбранного `voice_id`
- решение должно быть понятным и локальным для существующей data model
- не создавай ради этого тяжелую новую сущность
- если current user profile storage уже подходит, расширь его минимально
- ожидаемое поведение:
  - если user voice не выбран, использовать `default_voice_id` из TTS `/voices`
  - если выбран, использовать его для последующих озвучек
  - если выбранный voice исчез из `/voices`, поведение должно fail closed:
    - fallback на current TTS default voice
    - не ломать quiz flow

4. Listen action in learner runtime

- в тех learner quiz cards, где показывается английский текст для прослушивания, добавь `Listen`
- начни с минимального рабочего варианта:
  - question/review surfaces inside active training flow
  - оба основных типа заданий:
    - multiple choice
    - typed answer
- не надо в этой итерации внедрять TTS во все teacher/admin/workbook surfaces
- нажатие `Listen` должно:
  - определить английский текст текущего item/exercise
  - определить effective `voice_id`
  - вызвать TTS service
  - отправить пользователю voice/audio в Telegram
- quiz screen при этом не должен ломаться и не должен терять свое состояние

5. Voice selection UX

- добавь learner-facing voice selection flow, используя уже существующие Telegram menu/button/state patterns проекта
- не придумывай параллельную mini-app architecture
- UX должен быть компактным и понятным:
  - список голосов с human-readable names
  - текущий выбранный голос виден
  - если возможно локально и без UI расползания, покажи краткий subtitle вроде `Female, US`
- voice selection можно ввести через:
  - отдельную inline button рядом с `Listen`
  - или reuse существующего settings-style entrypoint, если это очевидно лучше по текущей архитектуре
- выбери меньший по сложности путь, но без архитектурного дублирования

6. Telegram delivery behavior

- сервис возвращает `audio/ogg`
- в Telegram отправляй это в форме, которая лучше соответствует UX произношения:
  - `send_voice`, если это хорошо ложится на текущий runtime
  - `send_audio`, только если это практичнее для already-existing abstractions
- выбор должен быть осознанным и минимальным
- если текущий transport cache layer можно безопасно использовать или подготовить под `voice` / `audio`, делай это только локально и без расползания scope
- не превращай эту итерацию в большой redesign media subsystem
- не вводи в этой итерации новую persistent asset truth for synthesized audio variants per `learning_item`

7. Error handling and fail-closed behavior

- если TTS service временно недоступен
- если timeout
- если service returns `400`
- если service returns `500`
- если Telegram reject'ит отправку audio/voice

Ожидание:

- бот не падает
- текущий learner session не теряется
- пользователь получает мягкое локализованное сообщение вроде:
  - `Could not play audio right now. Please try again.`
- текст quiz card и progression логика продолжают работать как обычно
- не показывай сырые stack traces или внутренние HTTP details пользователю
- в логах оставь достаточно сигнала для диагностики

8. English-only text boundary

- в TTS отправляй только сам английский текст, который нужно озвучить
- не включай туда служебные подписи, переводы, hints, markup или форматированные UI строки
- не синтезируй длинные mixed-language Telegram messages
- если текущий exercise surface содержит и English, и translated helper text, вытащи для TTS только нужный English fragment

9. Scope discipline

Минимальный практический scope этой итерации:

- config/env shape for optional TTS integration
- TTS client
- persisted user voice preference
- one compact voice chooser flow
- one compact `Listen` action in active learner training flow
- graceful error handling
- focused tests

Если останется время и это почти бесплатно:

- reuse того же listen entrypoint в homework-backed training, если он уже автоматически идет через те же question cards
- reuse того же listen entrypoint в topic-launched training, если он использует тот же runtime surface

Не делай в этой итерации:

- public TTS endpoint exposure
- webhook/service-to-service auth redesign
- массовый TTS rollout по teacher-content screens
- pre-generation or long-term storage of synthesized audio files in SQLite as runtime truth
- persistent per-item synthesized audio variants keyed by `learning_item` + `voice_id` + engine/model metadata
- background cache warming
- mandatory startup health gate on TTS
- new standalone TTS micro-domain inside EnglishBot
- broad media architecture rewrite

10. Data shape expectations

- если нужен новый user-level field для `voice_id`, выбери минимальную persistence форму
- если нужен отдельный helper/module для resolving effective voice, сделай его тонким
- если понадобятся env vars, они должны быть optional и clearly documented in `.env.example`
- if you touch Telegram media cache helpers at all, keep them transport-only; do not reinterpret them as the source of truth for synthesized audio content
- названия env vars выбери в текущем repo style, например:
  - `ENGLISHBOT_TTS_BASE_URL`
  - `ENGLISHBOT_TTS_TIMEOUT_SECONDS`
- но утверди только минимально нужный набор

11. Tests

Добавь focused tests минимум для:

- TTS-disabled runtime does not break core learner flow
- user without selected voice falls back to TTS default voice
- selected `voice_id` persists and is reused
- `Listen` action on an active learner item calls TTS client with only the expected English text
- typed-answer and multiple-choice learner surfaces both expose or reuse the listen path correctly, if they share one renderer
- temporary TTS failure returns a soft user-facing message and keeps the learner flow alive
- invalid or missing selected voice falls back safely to service default instead of crashing
- startup/config tests only if optional env wiring changes bootstrap behavior

12. Documentation updates

Обнови:

- `CHANGELOG.md`
- `context/current-state.md`
- `docs/architecture.md`, only if structural boundaries changed materially
- `.env.example`, if env vars were added

Current state should clearly say:

- TTS integration is optional and internal-only
- learner runtime can request pronunciation for English text through the separate TTS service
- user voice preference persists between sessions
- core bot runtime still does not depend on TTS to start or function
- existing Telegram media cache direction remains separate from core domain truth and is ready for future `audio` / `voice` reuse if that layer was touched
- persistent synthesized-audio variants per learning item are intentionally deferred to a later dedicated iteration

Ожидаемый итог:

- в active learner flow появляется минимальный `Listen` UX
- пользователь может выбрать и сохранить голос
- бот вызывает отдельный internal TTS service по internal hostname
- при проблемах с TTS learner flow не ломается
- интеграция остается optional, локальной и совместимой с current family-first architecture
- storage design for persistent synthesized audio variants remains a separate follow-up task instead of being folded into this first TTS slice
