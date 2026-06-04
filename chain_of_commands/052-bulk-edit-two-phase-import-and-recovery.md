Сделай в текущем репозитории EnglishBot следующую итерацию family-first bulk edit import reliability после `051-family-bulk-edit-via-xlsx.md`.


Use the agent workflow for this task.

Execution order:

1. architect
2. complexity_guard
3. coder

Read first:

* context/englishbot_handoff.md
* context/current_state.md
* AGENTS.md

Контекст:

- первая working version `/bulk_edit` уже есть
- workbook import сейчас делает:
  - validate workbook
  - backup SQLite
  - одну длинную write transaction
  - внутри этой transaction еще и скачивает remote assets по `image_ref` / `audio_ref`
- на больших импортах это создает проблемы:
  - долгий SQLite write lock
  - progress updates выглядят “подвисшими”
  - один медленный или timeout asset URL держит транзакцию открытой слишком долго
  - telemetry/audit/update side-effects могут упираться в `database is locked`

Задача этой итерации:

- сохранить backup-first discipline
- сохранить atomic DB apply semantics
- но убрать network/download phase из длинной DB transaction
- добавить более безопасную failure model для больших workbook imports с remote assets

Работай строго по правилам репозитория из `AGENTS.md`:

- не расширяй scope на старые workspace/publish flows
- читай только task-specific файлы по `docs/module-map.md`
- все bot-facing тексты только через `englishbot/i18n.py`
- новые или измененные команды обязательно проходят через `englishbot/command_registry.py`
- после завершения обнови `CHANGELOG.md`, `context/current-state.md` и `.env.example`, если появятся env changes
- держи `context/current-state.md` коротким

Перед реализацией подними только нужный контекст:

- `chain_of_commands/051-family-bulk-edit-via-xlsx.md`
- `englishbot/bulk_edit.py`
- `englishbot/bulk_edit_handlers.py`
- `englishbot/workbook_import.py`
- `englishbot/workbook_export.py`
- `englishbot/assets.py`
- `englishbot/db.py`
- focused bulk-edit/workbook tests

Главная архитектурная цель:

- import должен стать двухфазным:
  1. `prepare phase` вне DB write transaction
  2. `short atomic apply phase` внутри короткой transaction

Важно:

- это не значит “убрать transaction совсем”
- это значит “убрать внешние IO операции из длинной transaction”

Целевое поведение:

1. Backup как hard precondition

- до начала реальной обработки workbook backup должен быть создан обязательно
- если backup не создался:
  - import не начинается
  - session остается в понятном failure state
  - пользователю показывается короткое сообщение, что без backup apply не будет запущен

2. Prepare phase

- после successful workbook validation и successful backup import должен перейти в prepare phase
- prepare phase выполняется вне DB write transaction
- во время prepare phase нужно:
  - пройти по всем workbook rows
  - подготовить будущие row changes
  - скачать remote assets (`image_ref`, `audio_ref`) where needed
  - провалидировать скачанные assets
  - сохранить их как staged/local temp assets
  - собрать final prepared payload для DB apply

3. Asset staging

- remote asset downloads не должны сразу становиться частью active DB state
- нужна явная staged/prepared asset model хотя бы на уровне runtime/temp files
- если prepare phase падает на одном asset:
  - active family content в SQLite не должно быть изменено вообще
  - rollback DB state не нужен, потому что apply phase еще не начинался
  - staged temp files should be cleaned up where practical

4. Atomic apply phase

- если prepare phase успешно завершилась:
  - открывается короткая DB write transaction
  - import применяет только уже подготовленные data + staged local asset refs
  - transaction не должна зависеть от сети
  - transaction должна быть заметно короче, чем в текущей реализации
- apply phase по-прежнему должна:
  - update existing items by stable key
  - create new items
  - archive workbook-missing rows instead of hard delete
  - sync topics
  - keep `image_ref` as source of truth

5. Progress UX

- текущий progress indicator уже показывает processed rows
- следующая итерация должна показывать progress осмысленно по phase:
  - `Preparing assets`
  - `Prepared X/Y rows`
  - optionally current headword/item text
  - then `Applying database changes`
  - then completion summary
- не делай noisy message spam
- продолжай переиспользовать один control message

6. Failure model

Нужно явно разделить failure types:

- validation failed
- backup failed
- prepare failed
- apply failed

Для каждого из них нужен понятный status / user-facing message.

7. Emergency recovery helper

Добавь минимальный emergency restore mechanism from backup file, но не как основной happy path.

Ожидание:

- если apply phase сломалась уже после начала DB writes и normal rollback somehow is not enough or runtime decides DB may be unsafe
- должен существовать focused recovery helper, который может восстановить SQLite из backup file

Но:

- не превращай backup-restore в normal import strategy
- normal strategy все еще:
  - validate
  - backup
  - prepare outside transaction
  - short atomic apply

Если реализуешь restore helper:

- он должен быть очень явно ограничен
- должен fail closed
- должен использоваться только как emergency recovery path
- учитывай, что SQLite file replacement опасен при живых соединениях
- если нужен guarded application-level pause/close window, сделай это осознанно

8. Session statuses

При необходимости расширь bulk session statuses, например:

- `validating`
- `backing_up`
- `preparing`
- `applying`
- `failed_prepare`
- `failed_apply`
- `restoring_backup`

Но не делай статус-машину чрезмерно сложной. Она должна помогать support/debugging, а не мешать.

9. Asset and cleanup behavior

- staged downloaded files, которые не попали в committed apply, не должны бесконтрольно накапливаться
- после successful apply:
  - staged files становятся active local refs or are moved into final runtime location
- после failed prepare:
  - staged temp files cleanup where practical

10. Tests

Добавь focused tests минимум для:

- backup failure prevents any import work from starting
- prepare phase downloads/validates assets before DB write transaction
- failed remote asset download leaves SQLite unchanged
- failed image validation leaves SQLite unchanged
- apply phase uses pre-staged local asset refs and no network inside transaction
- progress callback distinguishes prepare progress from apply progress
- workbook-missing rows still archive instead of delete
- emergency restore helper behavior, if introduced
- cleanup of staged temp files on failed prepare / completed apply where practical

11. Documentation updates

Обнови:

- `CHANGELOG.md`
- `context/current-state.md`
- `docs/architecture.md`, only if structural boundaries changed materially

Current state should clearly say:

- family bulk import is now two-phase
- backup is required before processing starts
- remote assets are prepared outside DB write transaction
- DB apply stays atomic and short
- emergency restore helper exists only as a guarded fallback, if implemented

12. Non-goals

- не возвращай старую teacher workspace workbook architecture
- не добавляй Google APIs
- не делай distributed job queue
- не превращай bulk edit в background worker system
- не делай “partial success” import mode в этой итерации

Ожидаемый итог:

- большие workbook imports with remote assets становятся заметно надежнее
- progress в Telegram отражает реальную фазу работы
- долгие network IO больше не держат SQLite write transaction открытой
- backup остается обязательным guardrail
- atomic DB apply semantics сохраняются

