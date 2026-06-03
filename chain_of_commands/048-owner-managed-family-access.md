Сделай в текущем репозитории EnglishBot owner-managed privacy layer поверх уже готового family-first runtime, чтобы локальный бот не был “открытым для всех по /start”, а управлялся одним владельцем через env и одну техническую команду.

Работай строго по правилам репозитория из `AGENTS.md`:

- не расширяй scope дальше минимально нужного owner-flow
- читай только нужные файлы по `docs/module-map.md`
- все bot-facing тексты только через `englishbot/i18n.py`
- новые или измененные команды обязательно проходят через `englishbot/command_registry.py`
- после завершения обнови `CHANGELOG.md`, `context/current-state.md` и `.env.example`
- держи `context/current-state.md` коротким

Контекст:

- активный runtime уже family-first
- `/start` уже используется как точка входа для локального пользователя
- но сейчас нужна более приватная модель:
  - есть один owner Telegram user id
  - только owner может автоматически создать свою семью
  - остальные пользователи могут лишь зарегистрироваться
  - owner вручную добавляет их в свою семью технической командой

Целевое поведение:

- новая env-переменная:
  - `ENGLISHBOT_OWNER_TELEGRAM_USER_ID`
- если переменная задана:
  - только этот user id может на `/start` auto-bootstrap-ить `Home` family
  - любой другой пользователь на `/start` не получает семью автоматически
  - но пользователь должен быть сохранен в SQLite, чтобы owner потом мог его добавить
- owner получает техническую команду:
  - `/add_family <telegram_user_id>`
- эта команда:
  - доступна только owner user id
  - проверяет, что целевой пользователь уже зарегистрирован через `/start`
  - добавляет его в owner family
  - если owner family еще нет, создает ее
  - не должна молча перетаскивать пользователя из другой семьи

Что сделать по коду:

Шаг 1. Конфиг и env:

- добавь helper в `englishbot/config.py` для чтения `ENGLISHBOT_OWNER_TELEGRAM_USER_ID`
- если значение некорректно, fail closed с понятной ошибкой
- добавь переменную в `.env.example`

Шаг 2. Owner-aware `/start`:

- обнови active `/start` path в `englishbot/bot.py`
- поведение:
  - сохранить пользователя в базе
  - если owner env не задан:
    - оставить auto-bootstrap family behavior для локального простого режима
  - если owner env задан:
    - owner на `/start` получает auto-created `Home` family, если семьи еще нет
    - не-owner на `/start` получает только регистрацию и понятный ответ:
      - его `telegram_user_id`
      - просьбу попросить owner добавить его в семью
- если у пользователя семья уже есть, `/start` не должен ломать существующее состояние

Шаг 3. Family domain helper:

- в `englishbot/families.py` добавь маленькие focused helpers:
  - ensure owner family exists
  - add registered user to owner family
- если пользователь уже в owner family:
  - возвращай idempotent result
- если пользователь в другой семье:
  - кидай controlled error, не делай silent reassignment

Шаг 4. Техническая owner-команда:

- добавь новую command definition в `englishbot/command_registry.py`:
  - `/add_family`
- не регистрируй ее в публичный `BOT_COMMANDS`, если не хочешь светить техкоманду в UI
- создай отдельный focused handler, например `englishbot/owner_handlers.py`
- handler должен:
  - быть доступен только owner user id
  - парсить `/add_family <telegram_user_id>`
  - проверять, что целевой пользователь существует в `users`
  - если пользователь не зарегистрирован, отвечать “пусть сначала нажмет /start”
  - если пользователь уже в owner family, отвечать idempotent success-like status
  - если пользователь в другой семье, отвечать controlled conflict message

Шаг 5. Устрани конфликтующие `/start` handlers:

- проверь active router wiring
- убедись, что никакой generic `CommandStart()` handler из homework или legacy слоя не перехватывает `/start` раньше owner-aware bootstrap logic
- оставь один канонический `/start` path

Шаг 6. Тесты:

- добавь focused tests минимум для:
  - config helper for owner id
  - `/start` без owner env
  - `/start` для owner при заданном owner env
  - `/start` для non-owner при заданном owner env
  - `/add_family` success path
  - `/add_family` non-owner rejection
  - `/add_family` missing target user
  - `/add_family` idempotent already-in-family path
  - runtime regression test, где `/start` идет через `dispatcher.feed_update`, а не прямым вызовом handler, чтобы поймать router-order bugs

Шаг 7. Документация и state:

- обнови `CHANGELOG.md`
- обнови `context/current-state.md`
- явно запиши, что для локального privacy-first режима family bootstrap можно привязать к owner env

Ожидаемый итог:

- локальный бот больше не открывает семью всем подряд
- owner может сам bootstrap-ить семью
- остальные пользователи могут зарегистрироваться и показать owner свой `telegram_user_id`
- owner может вручную добавить их в семью командой `/add_family <telegram_user_id>`
- все это работает в обычном локальном запуске:
  - `python -m englishbot`

По коммиту:

- сделай отдельный commit slice с названием вроде:
  - `Add owner-managed family access`

По проверке:

- прогони узкий набор focused tests вокруг `bot`, `families`, `command_registry`, `i18n`, `bootstrap`
- если push доступен, запушь изменения после локальной проверки
