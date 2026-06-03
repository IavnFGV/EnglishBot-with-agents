Сделай в текущем репозитории EnglishBot два связанных улучшения для локального owner-managed family-first режима:

1. быструю owner-only команду для наполнения семейного контента демо-данными
2. глобальную защиту от Telegram no-op ошибки `Bad Request: message is not modified`

Работай строго по правилам репозитория из `AGENTS.md`:

- не расширяй scope дальше этих двух задач
- читай только нужные файлы по `docs/module-map.md`
- все bot-facing тексты только через `englishbot/i18n.py`
- новые или измененные команды проходят через `englishbot/command_registry.py`
- после завершения обнови `CHANGELOG.md`, `context/current-state.md` и `.env.example`, если нужны env changes
- держи `context/current-state.md` коротким

Контекст:

- active runtime уже family-first
- owner-managed privacy layer уже существует:
  - `ENGLISHBOT_OWNER_TELEGRAM_USER_ID`
  - `/start`
  - `/add_family <telegram_user_id>`
- для локального smoke test UX после bootstrap все еще не хватает быстрого способа наполнить семью контентом
- кроме того, Telegram часто шлет harmless ошибку `message is not modified` при повторном edit того же текста, и она не должна шуметь stack trace-ами

Цель по итоговому состоянию:

- owner может одной командой заполнить свою семью минимальным демо-контентом
- повторный вызов команды не должен плодить дубли
- Telegram no-op edit errors больше не должны захламлять runtime logs
- реальные другие `TelegramBadRequest` по-прежнему должны логироваться как ошибки

Шаг 1. Новая owner-only demo команда:

- добавь новую команду:
  - `/seed_demo`
- команда должна быть доступна только owner user id
- команда должна быть видима в обычном command menu, потому что это полезный локальный bootstrap tool для owner
- owner запускает команду и получает готовый минимальный набор family-first контента

Шаг 2. Demo content seed logic:

- положи seeding-логику в focused family/domain helper, а не в handler
- seed должен создавать owner family при необходимости
- seed должен добавить маленький демонстрационный набор:
  - тема `Seasons`
    - `spring`
    - `summer`
    - `autumn`
    - `winter`
  - тема `Colors`
    - `red`
    - `blue`
    - `green`
    - `yellow`
    - `black`
    - `white`
- добавь базовые переводы хотя бы для уже поддерживаемых языков интерфейса:
  - `ru`
  - `uk`
  - `bg`
- итог:
  - 2 темы
  - 10 слов

Шаг 3. Idempotent seeding:

- повторный `/seed_demo` не должен:
  - плодить дубли тем
  - плодить дубли learning items
  - бесконечно размножать связи topic-items
- команда должна возвращать понятный summary:
  - сколько тем создано на этом запуске
  - сколько items создано на этом запуске
  - сколько тем и items в самом seed-наборе

Шаг 4. UX integration:

- обнови `/start` owner message так, чтобы owner видел `seed_demo` среди ближайших шагов
- обнови `/help`, чтобы owner/local operator видел, что есть команда для быстрого заполнения семьи тестовым контентом

Шаг 5. Global no-op Telegram edit guard:

- в bot-level error handling добавь глобальную обработку для точной ошибки:
  - `TelegramBadRequest`
  - текст содержит `message is not modified`
- на этот кейс:
  - не писать stack trace как на unhandled exception
  - считать это harmless no-op
  - можно логировать только на `debug`
- при этом:
  - не глотай все `TelegramBadRequest`
  - например `message to edit not found` и другие реальные ошибки должны по-прежнему идти в error/exception path

Шаг 6. Локальный teacher-content regression fix:

- если где-то в teacher-content уже есть локальный safe wrapper вокруг overview edits, оставь его
- глобальный guard не заменяет локальные точечные fixups, а служит safety net для остальных мест

Шаг 7. Тесты:

- добавь focused tests минимум для:
  - command registry включает `/seed_demo` в видимый command list
  - `/start` owner message показывает `/seed_demo`
  - `/help` показывает `/seed_demo`
  - `/seed_demo` success path через `dispatcher.feed_update`
  - повторный `/seed_demo` остается idempotent
  - seed logic создает именно ожидаемые темы и количество items
  - global error handler игнорирует `message is not modified`
  - global error handler не глотает другой `TelegramBadRequest`

Шаг 8. Документация и state:

- обнови `CHANGELOG.md`
- обнови `context/current-state.md`
- явно запиши:
  - owner-managed local setups имеют `/seed_demo`
  - bot-level error handler globally ignores exact `message is not modified`

Ожидаемый итог:

- после локального `/start` owner может сразу нажать `/seed_demo`
- потом можно без ручного ввода контента прогнать:
  - `/topics`
  - `/learn`
  - `/teacher_content`
  - `/create_assignment`
- одинаковые Telegram edits больше не шумят stack trace-ами по всему боту

По коммитам:

- сделай отдельные конкретные commits, если удобно, например:
  - `Add owner demo content command`
  - `Ignore global no-op edit errors`

По проверке:

- прогони узкий набор focused tests вокруг:
  - `bot`
  - `families`
  - `command_registry`
  - `i18n`
  - `unhandled_logging`
  - teacher-content handler tests, если трогался локальный safe edit path

- если push доступен, запушь после локальной проверки
