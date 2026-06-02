Сделай в текущем репозитории EnglishBot не “адаптацию старой teacher/student workspace-системы”, а последовательный family-first rebuild с агрессивным удалением legacy-слоев, пока активный пользовательский путь не станет вмещаться в голову одного человека.

Работай строго по правилам репозитория из `AGENTS.md`:

- сначала ищи минимальное изменение, но если старый слой уже мешает новой простой модели, удаляй его, а не сохраняй ради совместимости
- читай только нужные файлы по `docs/module-map.md`
- не строй новые абстракции “на будущее”
- все bot-facing тексты только через `englishbot/i18n.py`
- новые или измененные команды проходят через `englishbot/command_registry.py`
- после каждого законченного шага обновляй `CHANGELOG.md`, `context/current-state.md` и `.env.example`, если трогались env vars
- держи `context/current-state.md` коротким, примерно до 150 строк

Контекст и целевое направление:

- deploy уже настроен, поэтому остаемся в этом же репозитории
- не нужно сохранять старую архитектуру ради прод-совместимости, потому что “старого продакшна” как ограничителя тут нет
- продукт должен стать family-first:
  - общий словарь семьи
  - общие темы семьи
  - личный прогресс
  - личные домашки
- не делать platform design
- не делать future-proofing
- не оставлять teacher/student workspace, publish, invite/join, topic grants как основу новой архитектуры

Цель по итоговому состоянию:

- active learner path должен быть family-first end to end
- active teacher/authoring path должен быть family-first end to end
- основные Telegram команды и flows должны работать без invite/join, publish, grants и без teacher workspace как обязательной сущности
- legacy код можно оставить только если он уже не участвует в живом продукте и явно считается cleanup baggage

Сначала зафиксируй решение в документах:

- добавь краткий execution brief в `docs/family-first-rebuild.md`
- обнови `docs/module-map.md`, `docs/architecture.md`, `context/current-state.md`
- прямо запиши, что мы остаемся в этом репозитории, а legacy teacher/student модель считается removal scope

Шаг 1. Добавь family-first persistence foundation:

- расширь SQLite schema в `englishbot/db.py`
- введи простую семейную модель:
  - `families`
  - `family_members`
  - family-owned `learning_items`
  - family-owned `topics`
  - `topic_items`
  - `user_progress`
  - `homework_assignments`
  - `homework_assignment_items`
- добавь focused family helpers в отдельный маленький модуль, например `englishbot/families.py`
- покрой это узкими тестами

Шаг 2. Переведи learner runtime на family-first:

- в `training.py` сделай так, чтобы `/learn` для пользователя в семье читал family-owned learning items
- не держи fallback в legacy workspace content для family users
- добавь focused tests

Шаг 3. Переведи homework на family-first:

- научи learner homework flow читать `homework_assignments`
- используй `training_sessions.family_homework_assignment_id`
- active homework list, start/resume, progress snapshot и completion должны работать на family homework
- focused tests в `tests/test_homework.py`, `tests/test_homework_handlers.py`, `tests/test_homework_dialog.py`, `tests/test_learner_homework.py`, `tests/test_training_handlers.py`

Шаг 4. Переведи topics на family-first:

- `topic_access.py` и `/topics` должны читать family topics напрямую
- убери зависимость learner topic flow от `student_topic_access`, grants и published student-workspace copies
- focused tests в `tests/test_topic_access.py` и `tests/test_topic_access_handlers.py`

Шаг 5. Переведи teacher-side assignment flow на family-first:

- `teacher_assignments.py`, `teacher_assignment_dialog.py`, `teacher_assignment_handlers.py`
- пусть `/create_assignment` работает через один виртуальный family workspace
- recipient list берется из `family_members`
- topic path и words path создают только family homework assignments
- не создавать assignments до confirm
- focused tests в `tests/test_teacher_assignment_handlers.py`

Шаг 6. Переведи teacher content authoring на family-first:

- `teacher_content.py`, `teacher_content_dialog.py`, `teacher_content_handlers.py`
- один shared family content surface
- topics/items/translations/assets редактируются только в family-owned content
- active authoring path больше не должен зависеть от teacher workspace creation, publish targets или student runtime workspaces
- `/teacher_content` и `/create_assignment` на входе должны требовать family membership, а не teacher role
- перепиши focused tests в `tests/test_teacher_content.py` и `tests/test_teacher_content_handlers.py`

Шаг 7. Агрессивно удаляй legacy runtime layers:

- удалить `teacher_student.py` и его tests, когда живые flows перестанут зависеть от invite scaffolding
- удалить `simple_mode.py` и все simple-mode branches
- удалить legacy Telegram handlers:
  - `admin_handlers.py`
  - `teacher_handlers.py`
  - `workbook_handlers.py`
- вычистить старые команды из `command_registry.py`, чтобы остался family-first набор:
  - `/start`
  - `/learn`
  - `/me`
  - `/settings`
  - `/cancel`
  - `/create_assignment`
  - `/topics`
  - `/teacher_content`
- не оставляй старые команды как видимую часть продукта; если временно нужно, пусть будут лишь deprecation stubs на короткое время, а потом удаляй

Шаг 8. Удали transitional admin/simple-mode/env tails:

- убрать `ENGLISHBOT_ADMIN_TELEGRAM_USER_ID`
- убрать `ENGLISHBOT_SIMPLE_MODE`
- удалить соответствующие helpers из `englishbot/config.py`
- обновить `.env.example`

Шаг 9. Схлопни dual-path domain code:

- `topic_access.py` должен стать family-only на active runtime path
- `homework.py` должен стать family-only на active runtime path
- `teacher_assignments.py` не должен падать обратно в workspace assignment creation
- `teacher_content.py` не должен держать active workspace/publish authoring path

Шаг 10. Оставь честный хвост в конце:

- если после всех product-path изменений останутся `workbook_export.py`, `workbook_import.py`, `workbook_admin.py` или `workspaces.py`, не тащи их обратно в active architecture
- в `context/current-state.md` и `docs/architecture.md` явно пометь их как legacy/offline/cleanup baggage
- не притворяйся, что они часть новой core модели

Ожидаемое финальное состояние:

- learner path family-first
- topics family-first
- homework family-first
- teacher content family-first
- assignment creation family-first
- invite/join/publish/grants/admin/simple-mode больше не часть живого продукта
- активная модель объясняется за 5 минут:
  - семья
  - члены семьи
  - слова семьи
  - темы семьи
  - личный прогресс
  - личные домашки

По коммитам:

- делай промежуточные коммиты после законченных волн cleanup
- названия коммитов должны описывать конкретный slice, например:
  - `Add family-first persistence foundation`
  - `Prefer family content for learn sessions`
  - `Delete simple mode bootstrap`
  - `Delete legacy topic and homework paths`
  - `Make teacher content family-only`

По тестам:

- не гони весь репозиторий на каждом шаге
- запускай только узкие релевантные тесты
- но перед финальным закрытием family-first волны прогони весь целевой набор learner/teacher/runtime tests, который покрывает active family-first path

Важно:

- не береги старую архитектуру
- если reuse existing module требует много костылей, перепиши локально проще
- если какой-то слой уже не нужен новому продукту, удаляй
- итоговый код должен быть меньше, прямее и спокойнее, чем исходная workspace-first система
