Сделай в текущем репозитории EnglishBot маленький UX-recovery slice для `aiogram-dialog` expired sessions: если пользователь нажимает старую inline-кнопку после перезапуска бота или истечения dialog session, бот должен не только логировать `UnknownIntent`, но и отправлять понятное восстановительное сообщение с просьбой начать сценарий заново.

Работай строго по правилам репозитория из `AGENTS.md`:

- держи изменение маленьким и локальным
- читай только нужные файлы по `docs/module-map.md`
- все bot-facing тексты только через `englishbot/i18n.py`
- после завершения обнови `CHANGELOG.md` и `context/current-state.md`
- не трогай unrelated dialog flows

Контекст:

- в активном runtime уже есть глобальный `on_error` handler в `englishbot/bot.py`
- `UnknownIntent` сейчас логируется как warning для наблюдаемости
- но UX плохой: пользователь ничего не понимает, когда нажимает устаревшую кнопку после restart/expired dialog context

Целевое поведение:

- если в `on_error` прилетает `UnknownIntent`
- бот:
  - продолжает писать warning в лог
  - пытается отправить пользователю короткое recovery-сообщение в чат
- сообщение должно:
  - объяснять, что экран/сессия уже не активны
  - мягко предполагать, что бот перезапустился или сессия истекла
  - просить открыть `/start` и начать сценарий заново
- если reply пользователю не удается отправить:
  - это не должно ломать error path
  - можно только залогировать локальную ошибку уведомления

Что сделать по коду:

Шаг 1. UnknownIntent recovery helper:

- в `englishbot/bot.py` добавь маленький helper для извлечения из `ErrorEvent`:
  - `user_id`
  - `chat_id`
  - bot object
- ориентируйся прежде всего на `callback_query`, потому что stale dialog intent обычно приходит от старых inline buttons

Шаг 2. User-facing recovery notice:

- в `on_error` для `UnknownIntent`:
  - сохрани текущий warning log
  - затем попробуй отправить recovery message пользователю
  - не роняй handler, если отправка не удалась

Шаг 3. I18n:

- добавь новый ключ в `englishbot/i18n.py` во все поддерживаемые языки:
  - `flow.session_expired`
- текст должен быть понятным и дружелюбным, без внутренних технических терминов

Шаг 4. Тесты:

- добавь focused tests минимум для:
  - `UnknownIntent` по-прежнему логируется как warning
  - `UnknownIntent` теперь отправляет recovery message пользователю
  - перевод `flow.session_expired` существует и содержит `/start`
- не расширяй scope на другие exception types

Шаг 5. Документация:

- обнови `CHANGELOG.md`
- обнови `context/current-state.md`
- явно зафиксируй, что expired dialog intents теперь не только видны в логах, но и восстанавливаемы с точки зрения UX

Ожидаемый итог:

- пользователь, нажавший старую кнопку после restart/expired dialog session, получает понятное сообщение вместо молчаливого сбоя
- логирование `UnknownIntent` остается
- recovery notice полностью идет через i18n
- поведение подтверждено focused tests

По коммиту:

- сделай отдельный commit slice с названием вроде:
  - `Notify users about expired dialog sessions`
