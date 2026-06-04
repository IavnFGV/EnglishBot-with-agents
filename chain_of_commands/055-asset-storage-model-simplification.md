Сделай в текущем репозитории EnglishBot узкое, но решительное упрощение модели хранения runtime-ассетов, чтобы поведение вокруг remote media, workbook import и локальных файлов стало понятным и предсказуемым без лишних сущностей, confusing naming и нагромождения одинаковых по смыслу файлов.


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

- сейчас нет такого production-like working runtime contract, который нужно бережно сохранять любой ценой
- локальную workbook-import media state можно смело reshaping'нуть и при необходимости просто переимпортить workbook заново
- главная задача этой итерации не “сохранить каждую текущую папку и filename”, а убрать нагромождение папок, дублей и confusing имен
- сейчас runtime asset model в целом рабочая, но слишком сложна для понимания
- для одной картинки одновременно фигурируют:
  - `source_url` в asset metadata
  - `local_path` в asset metadata
  - локальный файл на диске
- workbook import для remote `image_ref` / `audio_ref` скачивает файл локально, но кладет его в `assets/workbook-import/...`
- такие файлы могут использоваться как постоянные runtime assets, хотя по названию каталог выглядит как временный import staging
- если у URL нет удобного suffix, локальная копия может сохраняться как `.bin`, хотя по факту внутри это обычный image/audio file
- filenames слишком длинные и случайные, хотя у нас уже есть `asset_id` в таблице
- рядом могут жить одни и те же по смыслу файлы под разными именами и в разных каталогах
- в итоге поддержка и локальная разработка запутываются:
  - непонятно, что временное, а что постоянное
  - непонятно, какие файлы безопасно удалять
  - `.bin` выглядит как отдельный формат, хотя это просто fallback filename
  - “лес” из длинных uuid-like имен трудно соотносить с asset rows

Работай строго по правилам репозитория из `AGENTS.md`:

- не расширяй scope на старые workspace/publish flows
- читай только task-specific файлы по `docs/module-map.md`
- все bot-facing тексты только через `englishbot/i18n.py`
- новые или измененные команды обязательно проходят через `englishbot/command_registry.py`
- после завершения обнови `CHANGELOG.md`, `context/current-state.md` и `.env.example`, если появятся env changes
- держи `context/current-state.md` коротким

Перед реализацией подними только нужный контекст:

- `englishbot/assets.py`
- `englishbot/workbook_import.py`
- `englishbot/teacher_content.py`, only if asset write flow touches it
- focused tests:
  - `tests/test_workbook_import.py`
  - other focused asset tests only if directly relevant
- если понадобится deploy/runtime path context:
  - `docs/deploy.md`

Главная цель:

- сделать asset storage model проще в голове и в коде
- четко разделить:
  - original remote source metadata
  - active runtime local asset file
  - temporary import staging, if it still exists
- aggressively reduce folder and filename clutter instead of preserving it for compatibility

Важно:

- это не задача про redesign всего asset registry
- это не задача про новый media CDN
- это не задача про Telegram file-id persistence
- это не задача про удаление поддержки remote workbook refs
- это не задача про массовую миграцию старых assets без необходимости
- но это задача, где допустимо сознательно упростить локальную dev/runtime media layout и затем переимпортить workbook data, если это самый чистый путь

Целевое поведение:

1. One clear runtime source of truth

- для активного runtime asset бот должен использовать локальный файл
- `local_path` должен оставаться runtime source of truth
- `source_url` должен быть только metadata/traceability field, а не конкурирующим runtime source

2. Clear naming for persistent imported assets

- если workbook import сохраняет remote image/audio локально и этот файл становится частью живого runtime state:
  - он не должен лежать в confusing pseudo-temp path вида `assets/workbook-import/...`, если это уже постоянный asset
- выбери более понятное постоянное место, например что-то в духе:
  - `assets/images/imported/...`
  - `assets/audio/imported/...`
  - или другой минимальный, но ясный naming
- если staging phase все еще нужна:
  - staging path и final runtime path должны быть явно разными по смыслу

3. Short deterministic runtime filenames

- не используй длинные случайные runtime filenames там, где у нас уже есть `assets.id`
- предпочти короткую предсказуемую схему именования, привязанную к записи asset registry, например в духе:
  - `asset-<asset_id>.jpg`
  - `asset-<asset_id>-primary.jpg`
  - `asset-<asset_id>-0.jpg`
- если нужен временный файл до появления final `asset_id`:
  - temporary name допустим только на staging phase
  - после final DB apply живой runtime asset должен получить короткое понятное имя
- цель:
  - убрать “лес” из длинных uuid-like имен
  - сделать ручной осмотр папки с assets понятным
  - сделать связь file <-> asset row легче для debugging/support

4. No misleading `.bin` runtime assets

- не сохраняй живые runtime image/audio files под `.bin`, если реальный формат можно определить
- минимально допустимые варианты:
  - взять extension из validated content format
  - fallback на sensible type-specific extension
- цель:
  - по имени файла должно быть примерно понятно, что это image/audio asset, а не нечто неопределенное

5. Minimal model, not extra layers

- не добавляй новую сложную сущность поверх уже существующего `assets` registry
- по возможности оставь простую модель:
  - `source_url` optional
  - `local_path` required for active runtime file
  - один локальный файл на диске
- не держи несколько постоянных локальных копий одного и того же asset только из-за исторического workflow naming
- если import использует staging:
  - staging должен быть чисто техническим prepare-phase detail, а не долговечной частью business model

6. Safe cleanup semantics

- после successful apply workbook-import staged temp files не должны бесконтрольно копиться
- если staged file move/rename нужен для перехода в final runtime path:
  - делай это явно и предсказуемо
- если import падает до commit:
  - temporary staged files should be cleaned up where practical

7. Preserve current product behavior

- не ломай существующее поведение teacher content image/audio editing
- не ломай workbook import remote media support
- не делай сеть обязательной в runtime question rendering
- не возвращай runtime dependence on external URLs
- но не сохраняй confusing folder/file layout только ради backwards compatibility в локальной dev DB, если переимпорт дает более чистый результат

8. Tests

Добавь focused tests минимум для:

- imported remote image gets stored under the new persistent runtime path instead of confusing workbook-import path
- imported remote audio follows the same rule, if audio path is touched in this slice
- final runtime filenames are short and deterministic, based on persisted asset identity instead of long random names
- runtime asset filenames use sensible extensions instead of `.bin`
- prepare/apply cleanup semantics remain correct if staging is still used
- existing local-path behavior remains compatible

9. Documentation updates

Обнови:

- `CHANGELOG.md`
- `context/current-state.md`
- `docs/architecture.md`, only if structural boundaries changed materially

Current state should clearly say:

- runtime assets still use local files as the source of truth
- workbook-import remote media no longer lands in a misleading quasi-temp permanent path
- imported runtime assets now use clearer naming, shorter deterministic filenames, and sensible file extensions

10. Non-goals

- не делать полный asset lifecycle manager
- не добавлять background garbage collector
- не чинить все historical assets in one risky migration unless absolutely needed
- не вводить отдельную таблицу только ради temporary staging
- не превращать эту задачу в большой storage subsystem rewrite

Ожидаемый итог:

- модель хранения ассетов станет проще объяснять и поддерживать
- станет ясно, что является runtime asset, что metadata, а что temporary staging
- исчезнет confusing `.bin`/`workbook-import` permanent runtime storage story
- исчезнет нагромождение длинных случайных имен там, где можно использовать короткие asset-id-based filenames
- при этом текущий family-first runtime и workbook import не потеряют рабочее поведение
