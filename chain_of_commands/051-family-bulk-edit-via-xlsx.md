Сделай в текущем репозитории EnglishBot первую рабочую итерацию family-first bulk editing через `.xlsx`, опираясь на уже существовавший в истории проекта workbook import/export flow, но верни его только в упрощенном виде и только под текущую семейную модель.

Работай строго по правилам репозитория из `AGENTS.md`:

- не пытайся вернуть старую workspace/publish архитектуру
- читай только нужные файлы по `docs/module-map.md`
- все bot-facing тексты только через `englishbot/i18n.py`
- новые или измененные команды обязательно проходят через `englishbot/command_registry.py`
- после завершения обнови `CHANGELOG.md`, `context/current-state.md` и `.env.example`, если появятся env changes
- держи `context/current-state.md` коротким

Перед реализацией обязательно подними исторический контекст:

- `chain_of_commands/017-export`
- `chain_of_commands/018-import.md`
- `chain_of_commands/019-import-export-from-bot.md`
- `chain_of_commands/033-import-export revisit`
- релевантные куски `context/englishbot_handoff.md` про workbook format и backup-before-import

Важно:

- в истории import/export через `.xlsx` уже работал достаточно неплохо
- его не нужно заново изобретать
- нужно вернуть полезную механику и адаптировать ее к текущему family-first runtime
- никаких Google Drive / Google Sheets API в этой итерации

Цель продукта:

- редактирование слов по одному через Telegram больше не должно быть единственным realistic authoring path
- любой член семьи может войти в bulk edit режим
- бот экспортирует семейный контент в `.xlsx`
- пользователь редактирует файл локально или вручную в Google Sheets после самостоятельной загрузки туда
- затем отправляет `.xlsx` обратно в бота
- бот валидирует, делает backup и атомарно применяет изменения к активной family content базе

Главное упрощение по сравнению с прошлыми попытками:

- одна активная bulk edit session на весь бот
- пока она активна, весь бот находится в gated maintenance-like режиме
- любые обычные команды и флоу не исполняются
- пользователи получают короткое служебное сообщение, что идет bulk edit session
- инициатор bulk edit может:
  - загрузить `.xlsx`
  - применить загруженный файл
  - продлить сессию
  - завершить сессию без импорта
- сессия автоматически истекает по таймауту, если ее не продлили

Целевое поведение v1:

1. Bulk edit entrypoint:

- добавь entrypoint в активный teacher/family authoring UX
- это может быть кнопка в `/teacher_content` и/или отдельная техническая команда
- не усложняй выбором режимов
- вход в bulk edit должен быть доступен любому члену семьи

2. Global bulk session:

- добавь persisted bulk edit session model, например в `db.py` + focused module
- минимум полей:
  - `id`
  - `family_id`
  - `started_by_user_id`
  - `status` (`active`, `uploaded`, `applying`, `expired`, `cancelled`, `completed`, `failed`)
  - `export_file_path`
  - `uploaded_file_path`
  - `backup_file_path`
  - `expires_at`
  - `created_at`
  - `updated_at`
- в один момент времени допускается только одна active/uploaded/applying session на весь бот

3. Global gate:

- пока bulk edit session активна:
  - бот не должен выполнять обычные команды и dialog flows
  - это относится ко всему active runtime, а не к выборочным flows
- вместо “тишины” бот должен отвечать коротко и понятно:
  - для обычных пользователей: идет bulk editing, попробуйте позже
  - для инициатора: bulk editing активен, загрузите файл или завершите сессию
- если bulk session истекла, gate снимается автоматически

4. Session timer UX:

- стартовая длительность: `30 minutes`
- инициатор может продлить еще на `30 minutes`
- не делай шумных minute-by-minute напоминаний
- достаточно:
  - одно сообщение при старте
  - reminder за `10 minutes`
  - reminder за `3 minutes`
  - сообщение об automatic expiration
- если уместно, используй один control message с кнопками и обновляй его, но не переусложняй

5. Export format:

- верни workbook export/import как family-first projection
- не используй старую teacher workspace model
- экспортируй только контент текущей семьи
- ориентируйся на лучший уже существовавший human-editable workbook format из истории
- если формат нужно упростить, упрощай осознанно, но не теряй читаемость

Минимум по workbook contract:

- workbook должен быть человеко-редактируемым
- workbook не должен быть raw DB dump
- нужно использовать стабильную workbook identity, например `item_key`
- import/export должны быть deterministic

6. Image columns:

- это обязательное требование этой итерации:
  - рядом с `image_ref` должно быть поле `image`
  - `image` существует только для наглядности
  - оно должно экспортироваться как Google Sheets `IMAGE()` formula
- source of truth:
  - `image_ref`
- import behavior:
  - `image` column полностью игнорируется
  - даже если пользователь его менял, import не должен читать его как источник данных
- это обязательно явно зафиксируй в коде, тестах и документации

7. Import behavior:

- import должен быть atomic
- сначала полная validation
- потом backup
- потом одна write transaction
- missing rows из workbook:
  - не hard delete
  - archive existing family content instead
- обновления:
  - существующие строки обновляются по stable key
  - новые строки создаются
- topic membership должна синхронизироваться из workbook
- archive semantics должны оставаться soft/archive-based

8. Backups:

- перед apply всегда делай full SQLite backup
- используй текущий backup directory из env/runtime
- backup filename должен быть человекочитаемым и отражать bulk edit context, например:
  - `before-bulk-edit__family-12__user-874778749__2026-06-03T19-10-00.sqlite3`
- если в проекте уже был retention pattern для workbook backups, аккуратно верни его в минимально нужном виде

9. Upload/apply flow:

- после старта bulk session бот:
  - экспортирует `.xlsx`
  - отправляет файл инициатору
  - показывает control actions
- когда пользователь загружает `.xlsx` обратно:
  - бот не применяет сразу
  - бот сохраняет uploaded candidate
  - пишет, что файл получен
  - предлагает `Apply` или `Cancel`
- при `Apply`:
  - validation
  - backup
  - one transaction import
  - session complete
  - gate release
  - summary with counts: created / updated / archived / unchanged / errors if any

10. Expiration/cancel:

- при manual cancel:
  - session closes
  - gate releases
  - uploaded/export temp files cleanup where practical
- при automatic expiration:
  - session moves to `expired`
  - gate releases
  - user gets short expiration message

11. Architecture boundaries:

- workbook business logic должна жить в focused modules, а не в `bot.py`
- Telegram layer должен быть thin orchestration
- не превращай teacher handlers в catch-all monster
- можно вернуть dedicated modules вроде:
  - `englishbot/workbook_export.py`
  - `englishbot/workbook_import.py`
  - `englishbot/bulk_edit.py`
  - `englishbot/bulk_edit_handlers.py`
- но только если это действительно минимальный и чистый способ

12. Commands and UI:

- если нужен новый command для первой итерации, добавь его через `command_registry.py`
- если bulk edit идет только из `/teacher_content`, это тоже допустимо
- не делай широкий админский UX
- keep it practical and testable

13. Tests:

- добавь focused tests минимум для:
  - creating a bulk edit session
  - only one active bulk session globally
  - global gate blocks ordinary bot flows while bulk edit is active
  - initiator gets the specialized bulk-edit-active response
  - session expiration releases the gate
  - export creates a valid `.xlsx`
  - import validates before writing
  - import ignores `image` column completely
  - export includes `image` column as `IMAGE()` display formula next to `image_ref`
  - import updates existing items by stable key
  - import creates new items
  - missing rows become archived instead of deleted
  - backup file is created before apply
  - apply runs in one transaction
  - upload then apply flow through Telegram layer

14. Documentation updates:

- обнови `CHANGELOG.md`
- обнови `context/current-state.md`
- при необходимости обнови `docs/architecture.md`

Current state must mention:

- family-first bulk edit via local `.xlsx` exists
- only one bulk edit session may be active
- active bulk session gates the bot globally
- workbook import is atomic and backup-first
- missing workbook rows archive family content rather than hard-delete it
- `image_ref` is the source of truth
- `image` is display-only and exported as `IMAGE()` formula

Ожидаемый итог:

- семья может редактировать контент bulk-режимом через `.xlsx`
- старый полезный workbook/import-export опыт возвращен из истории
- текущая family-first runtime model не размывается
- никаких Google APIs в первой итерации
- решение проще и надежнее, чем прошлые переусложненные попытки

По коммитам:

- режь работу на понятные slices, например:
  - `Restore family workbook export/import core`
  - `Add global bulk edit session gate`
  - `Wire bulk edit flow into teacher UI`

По проверке:

- прогони узкий набор focused tests вокруг:
  - workbook export/import
  - bulk edit session domain
  - Telegram bulk edit handlers
  - bot-wide gate behavior

- если push доступен, запушь изменения после локальной проверки
