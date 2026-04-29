# Archived note

This document is historical and mixed-purpose. It contains useful terminology and older target-design notes, but it is no longer the recommended read-first file for routine tasks.

Read order for current work:
1. `AGENTS.md`
2. `docs/module-map.md`
3. `docs/architecture.md`
4. `context/current-state.md`

# EnglishBot: техническая спецификация

Этот документ описывает две вещи одновременно:

- `Current behavior` — что уже реализовано в репозитории сейчас.
- `Target behavior` — целевая архитектурная модель, к которой проект должен двигаться.

Это не переписывание ТЗ с нуля и не отдельный changelog. Задача документа:

- зафиксировать инварианты продукта и архитектуры;
- явно отметить, что уже внедрено;
- сохранить будущие design sections как целевое направление;
- не допускать противоречий с `context/current-state.md`.

Любая новая функциональность должна:
- вписываться в эту модель;
- не ломать описанные инварианты;
- не откатывать систему к teacher-student-first подходу.

---

## 1. Термины

### learning_item

Основная учебная единица системы. Не "слово" как таковое, а объект обучения, привязанный к workspace.

Сейчас:
- runtime-модель строится вокруг `learning_items`;
- headword хранится в `lexemes`;
- переводы хранятся в `learning_item_translations`.

---

### workspace

Граница владения контентом и доступа.

Сейчас:
- есть явные `teacher` и `student` workspace;
- у контента есть `workspace_id`;
- доступ определяется через `workspace_members`.

---

### publish

Операция копирования контента из teacher workspace в student workspace.

Сейчас:
- publish уже реализован как локальное копирование;
- live-связи между workspace не используются;
- для трассировки допускаются только `source_*` поля.

---

### workbook import

Загрузка teacher workbook из локального `.xlsx` в один teacher workspace через канонический человеко-редактируемый workbook format.

Сейчас:
- поддерживается только локальный `.xlsx` import;
- Google Sheets API нет;
- versioning и diff sync нет.

---

### seed / bootstrap

`bootstrap` — создание и миграция SQLite-схемы при старте.

`seed` — начальное наполнение starter content в дефолтном teacher workspace.

Сейчас:
- bootstrap создаёт схему и нужные миграции;
- seed добавляет starter vocabulary packs в workspace `Starter Content`.

---

### assignment

Фиксированное задание для ученика в student workspace.

Сейчас:
- assignment хранит snapshot списка `learning_item_id`;
- assignment имеет собственный title;
- assignment не пересчитывается из topic постфактум.

---

### training session

Фиксированная сессия обучения поверх конкретного набора item-ов.

Сейчас:
- training session хранит snapshot item-ов;
- `training_session_items` фиксирует `prompt_text` и `expected_answer`;
- активная сессия не меняется после старта.

---

### exercise instance

Конкретное упражнение, показанное ученику внутри training session.

Сейчас:
- отдельной exercise-модели в runtime пока нет;
- текущий MVP фактически использует один plain-text question/answer flow поверх `training_session_items`.

---

### bot_language

Язык bot-facing интерфейса.

Сейчас:
- хранится в `user_profiles.bot_language`;
- управляет командами, кнопками и прочим интерфейсным текстом бота.

---

### hint_language

Язык learner-facing подсказок и exercise hints.

Сейчас:
- хранится отдельно в `user_profiles.hint_language`;
- настраивается независимо от `bot_language` через `/settings`;
- используется для learner-facing hint language в упражнениях.

---

## 2. Что это за продукт

`EnglishBot` — Telegram-first бот для изучения английских слов и коротких выражений.

Основной продуктовый сценарий:

1. контент создаётся и редактируется учителем;
2. контент публикуется в пространство обучения;
3. ученик проходит обучение через Telegram;
4. бот задаёт вопросы, проверяет ответы и считает прогресс;
5. учитель отслеживает прогресс и управляет заданиями.

### Current behavior

- бот уже работает как Telegram-first продукт на `aiogram`;
- runtime source of truth — SQLite, не JSON;
- `/start` сейчас homework-first для студентов;
- `/learn` остаётся fallback-сценарием для минимальной тренировки;
- optional AI/TTS/WebApp не обязательны для core runtime.

### Target behavior

- Telegram остаётся основным клиентом обучения;
- расширения не должны превращать продукт в "AI playground";
- core flow остаётся teacher -> publish -> student learning.

---

## 3. Архитектурный принцип

Система строится как модульный монолит.

Ключевое требование:

> Бизнес-логика должна быть отделена от Telegram-слоя.

Telegram-слой:
- только оркестрирует UX;
- не содержит бизнес-решений.

### Current behavior

- это уже соблюдается как основное направление;
- persistence и business flows вынесены в отдельные модули;
- Telegram handlers в основном остаются thin wrappers над сервисной логикой.

### Target behavior

- новые фичи должны продолжать усиливать это разделение;
- нельзя переносить publish, assignment, workbook, access-правила в handlers.

---

## 4. Базовая продуктовая модель

### Роли

Система поддерживает роли:

- `teacher`
- `student`
- `self-learner` — как целевой режим

### Current behavior

- persisted profile role уже есть;
- основные рабочие роли сейчас — `teacher` и `student`;
- self-learner как полноценный отдельный product flow ещё не реализован;
- текущий self-use сценарий ограничен self-invite/self-link для тестирования.

### Target behavior

- teacher создаёт и публикует контент, назначает задания, отслеживает прогресс;
- student проходит обучение и выполняет задания;
- self-learner должен уметь работать без отдельного учителя, не ломая workspace-first модель.

---

## 5. Workspace-first модель

Система строится вокруг `workspace ownership`, а не вокруг teacher-student связей.

### Current behavior

- workspace foundation уже есть;
- существуют явные `teacher` и `student` workspace;
- `workspace_members` — источник истины для membership и runtime access;
- команды teacher-topic/workbook уже требуют явный `workspace_id`;
- отдельного workspace UI и workspace selection flow пока нет;
- в части legacy/compatibility остаётся детерминированный default authoring workspace, и `/learn` fallback всё ещё опирается на него.

### Target behavior

- все ключевые domain-решения должны принимать явный workspace context;
- implicit selection workspace не должен становиться нормой;
- система должна развиваться в сторону полного workspace-first, а не обратно в teacher-student-first.

---

## 5.1 Типы workspace

### Teacher workspace (authoring)

Используется для:

- создания контента;
- редактирования learning items;
- подготовки тем и учебных единиц;
- workbook import/export.

#### Current behavior

- teacher workspace уже является контейнером авторского контента;
- `topics` и `learning_items` принадлежат teacher workspace через `workspace_id`;
- workbook admin flows работают только для teacher workspace;
- edit/import/archive операции ограничены teacher membership.

#### Target behavior

- teacher workspace может содержать одного или нескольких учителей;
- только участники с ролью `teacher` могут редактировать;
- teacher workspace остаётся source-of-truth для authoring.

---

### Student workspace (learning)

Используется для:

- прохождения обучения;
- хранения прогресса;
- выполнения заданий;
- topic access;
- runtime copies опубликованного контента.

#### Current behavior

- student workspace уже используется как runtime learning boundary;
- assignments, training sessions и topic access живут в student workspace;
- publish копирует контент в student workspace;
- в текущем MVP типичный student workspace создаётся как shared workspace для teacher-student pair.

#### Target behavior

- student workspace может содержать одного или нескольких учеников и учителей;
- student workspace должен оставаться независимым от последующих правок teacher workspace, кроме явного повторного publish.

---

## 5.2 Участники workspace

Участники хранятся в `workspace_members`.

### Current behavior

- membership уже используется для доступа к assignments, topic access, homework visibility и topic visibility;
- teacher-student link больше не является источником истины для runtime access;
- роли участников сейчас минимальны: `teacher` и `student`.

### Target behavior

#### teacher
- редактирует контент в teacher workspace;
- публикует контент;
- назначает задания;
- управляет доступом;
- просматривает прогресс.

#### student
- проходит обучение;
- не редактирует authoring content.

---

## 5.3 Правила multi-teacher

Система поддерживает нескольких учителей, но с упрощённой моделью:

- все учителя равны;
- нет владельца workspace;
- нет уровней доступа;
- нет разрешения конфликтов;
- `last-write-wins` допустим.

### Current behavior

- data model уже не запрещает движение в эту сторону;
- но текущий MVP всё ещё уже и чаще работает через pair-based shared student workspaces;
- отдельной развитой multi-teacher coordination модели пока нет.

### Target behavior

- multi-teacher допускается как упрощённая модель без ownership hierarchy.

---

## 6. Контент и владение

### Инвариант

> Контент принадлежит workspace, а не пользователю.

### Current behavior

- `learning_items` и `topics` уже принадлежат workspace;
- `learning_items` и `topics` принадлежат workspace и имеют внутренние stable workbook keys для legacy/runtime нужд, но workbook import/export больше не экспонирует их пользователю;
- `learning_item_translations` принадлежат learning item и не вводят отдельное владение;
- опубликованные student copies сохраняют собственные локальные id и workbook keys, но могут хранить `source_learning_item_id` или `source_topic_id`.

### Target behavior

#### Teacher workspace
- источник авторского контента.

#### Student workspace
- получает контент только через publish;
- работает с локальной копией, а не с живой ссылкой на teacher workspace.

---

## 7. Workbook model

Workbook — это teacher-side bulk editing format, а не отдельный runtime source.

### Current behavior

- workbook export/import работают только для одного teacher workspace за раз;
- canonical workbook содержит только листы:
  - `meta`
  - `learning_items`
- `meta` хранит `version`, `default_workspace`, `default_translation_language`;
- `learning_items` хранит human-facing flattened rows: `text`, tagged `translations`, `workspace`, `topic`, `image_url`, `image_preview`, `audio_url`, `audio_voice`, `is_archived`;
- import полностью валидирует workbook до записи и потом выполняет один explicit write transaction;
- до записи import создаёт SQLite backup и хранит только последние 500 workbook-import backup файлов;
- import больше не принимает legacy workbook sheets, workbook ids, db ids или workbook-key assumptions как внешнюю contract surface;
- archive semantics поддерживаются через archive flags, а не physical delete;
- media хранится канонически через `assets` и `learning_item_assets`, а не через direct fields на `learning_items`;
- translations в workbook используют multiline syntax вроде `<ru>: ...`, а строка без тега трактуется как `default_translation_language`;
- для текущей фазы import валидирует workspace/topic names как globally unique simple keys вместо большого migration проекта.

### Target behavior

- workbook остаётся teacher authoring tool поверх workspace-owned content;
- workbook import/export не должен обходить workspace ownership и publish boundary;
- до отдельного product-решения workbook не превращается в live sync систему.

### Current constraints

- нет versioning;
- нет diff sync;
- нет Google Sheets API;
- нет merge/conflict resolution.

---

## 8. Publish

Контент не используется напрямую между workspace.

Используется операция:

> publish (копирование)

### Current behavior

- publish уже используется в assignment и topic access flows;
- teacher content копируется в student workspace как локальная runtime copy;
- published copies переиспользуются по `source_*` id, когда это возможно;
- после publish student workspace не зависит от live edits teacher workspace.

### Target behavior

- учитель выбирает контент;
- система копирует его в student workspace;
- student workspace остаётся самостоятельным;
- между workspace нет live-ссылок.

### Инвариант

- допускаются только trace/reference поля вида `source_*`;
- back-sync из student workspace в teacher workspace не предполагается.

---

## 9. Assignment

Assignment — фиксированное задание.

### Current behavior

- assignment хранит фиксированный список student-workspace `learning_item_id`;
- title assignment сохраняется как snapshot-readable название;
- assignment может быть создан напрямую по item id или через topic-based flow;
- после создания assignment не зависит от последующих изменений topic membership, topic title или teacher-side content edits.

### Target behavior

При создании:
- фиксируется список `learning_item_id`;
- сохраняется название.

Инварианты:
- assignment не зависит от topic;
- изменения topic не влияют на assignment.

---

## 10. Training session

Training session — snapshot обучения поверх уже выбранных item-ов.

### Current behavior

- training session фиксирует ordered list `learning_item_id`;
- `training_session_items` также сохраняет `prompt_text` и `expected_answer`;
- in-flight session не меняется после старта даже при изменении контента;
- один и тот же training flow переиспользуется и для `/learn`, и для homework/topic launches.

### Target behavior

- training session фиксирует список `learning_item_id`;
- training session хранит snapshot конкретных упражнений сессии, а не только ссылку на mutable content;
- не изменяется после старта.

---

## 10.1 Exercise model

Exercise model нужен для перехода от одного plain-text question/answer flow к staged exercises.

### Target behavior

- `learning_item` — это content unit;
- exercise instance — это конкретный вопрос, показанный в рамках сессии;
- training session snapshot — это зафиксированное session state поверх mutable content;
- одна и та же content unit может порождать разные exercise instances.

Exercise stages:
- `easy`
- `medium`
- `hard`

Exercise types:
- `multiple_choice`
- `jumbled_letters`
- `typed_answer`

Инварианты:
- stage и type относятся к exercise instance, а не к `learning_item` как content object;
- training session не должен зависеть от последующих правок content после старта.

---

## 10.2 Initial completion rules

### Target behavior

- каждый `learning_item` начинается со стадии `easy`;
- для перехода дальше нужны 2 correct answers на `easy`;
- затем нужны 2 correct answers на `medium`;
- после этого `learning_item` считается completed;
- 4 correct answers in a row открывают `hard`;
- `hard` остаётся optional и не блокирует completion;
- если `hard` ещё не открыт, UI должен показывать `medium`;
- должен быть явный способ skip `hard`.

---

## 10.3 Language split for exercises

### Current behavior

- bot-facing UI language уже существует как `bot_language`;
- learner-facing exercise hint language уже существует как отдельный `hint_language`.

### Target behavior

- `bot_language` управляет bot-facing interface text;
- `hint_language` управляет learner-facing hint language для упражнений;
- эти настройки не должны смешиваться как одна и та же сущность.

---

## 10.4 Runtime UI note

Это runtime/transport note, а не core domain model.

### Target behavior

- во время сессии может редактироваться одно progress message;
- одно active question message может заменяться следующим;
- Telegram message management относится к transport/runtime behavior, а не к core domain model.

---

## 11. Разделение состояний

### Mutable

- topics
- learning_items
- translations

### Snapshot

- assignments
- training_sessions
- exercise instances внутри training session

### Current behavior

- mutable authoring content уже отделён от snapshot runtime сущностей;
- archive/edit/import/publish меняют authoring state;
- assignments и active/completed training sessions не должны переписываться задним числом.

### Инвариант

> Mutable изменения не ломают snapshot.

---

## 12. Удаление

Используется soft delete / archive-first подход.

### Current behavior

- в рабочем MVP основной lifecycle — archive, а не hard delete;
- archived content скрывается из обычных discovery/list flows, но остаётся читаемым по id там, где это нужно для historical/runtime сценариев;
- workbook import и teacher content flows должны уважать archive flags.

### Target behavior

- допускаются поля уровня `is_archived` / `is_deleted`;
- нельзя ломать сущности, уже попавшие в assignment или training session.

---

## 13. Teacher-Student связь

Teacher-student связь используется как onboarding bridge, но не как runtime ownership model.

### Current behavior

- invite/join flow уже существует;
- teacher-student link всё ещё используется как bridge для onboarding и для поиска shared student workspace в текущем MVP;
- при этом runtime access, assignment ownership, topic access и visibility определяются через `workspace_members`.

### Target behavior

- teacher-student связь используется только для:
  - onboarding
  - приглашений
- доступ определяется через:
  - `workspace_members`

---

## 14. Self-learner режим

### Current behavior

- полноценный self-learner product flow пока не реализован;
- есть только ограниченный self-invite/self-link сценарий для self-testing.

### Target behavior

- пользователь может иметь свой student workspace;
- режим должен работать без обязательного учителя;
- реализация не должна ломать общую workspace-first модель.

---

## 15. Данные

Основные сущности:

- `users`
- `user_profiles`
- `workspaces`
- `workspace_members`
- `teacher_student_links`
- `invites`
- `lexemes`
- `learning_items`
- `learning_item_translations`
- `topics`
- `topic_learning_items`
- `student_topic_access`
- `assignments`
- `assignment_items`
- `training_sessions`
- `training_session_items`

### Current behavior

- SQLite уже является runtime source of truth;
- основная единица обучения — `learning_item`, не plain word;
- `lexemes` остаются глобальными;
- headword живёт в `lexemes.lemma`;
- переводы живут в `learning_item_translations(language_code, translation_text)`;
- topic membership живёт в `topic_learning_items`;
- current topic ordering остаётся неявным и определяется relation-row insertion order;
- workbook persistence mappings уже согласованы с текущим кодом:
  - workbook `learning_items.workspace` / `meta.default_workspace` -> `workspaces.name` validation against target teacher workspace
  - workbook `learning_items.topic` -> `topics.name` / `topics.title`
  - workbook `learning_items.text` -> `learning_items.text`
  - workbook multiline `translations` -> `learning_item_translations(language_code, translation_text)`
  - workbook `image_url` -> linked `image` asset with role `primary_image`
  - workbook `image_preview` -> linked `image` asset with role `image_preview`
  - workbook `audio_url` -> linked `audio` asset with role `primary_audio`
  - workbook `audio_voice` -> linked `voice` asset with role `audio_voice`

### Target behavior

- доменная модель продолжает строиться вокруг `learning_item`, а не вокруг слова как единственной сущности;
- новые фичи не должны уводить runtime назад в JSON-first или handler-first хранение.

---

## 16. Telegram и текущие операционные потоки

Этот раздел описывает именно текущую реализацию и нужен для того, чтобы ТЗ не противоречило реальному продукту.

### Current behavior

- `/start` — homework-first entry point для студентов;
- `/learn` — минимальная fallback training flow;
- `/settings` — выбор языка интерфейса;
- `/invite` и `/join` — onboarding bridge для teacher-student связи;
- `/assign` — создание assignment:
  - либо по списку item id;
  - либо по `teacher_workspace_id + topic_name`;
- `/granttopic` — publish topic в student workspace и grant topic access;
- `/topics` — список доступных learner topics;
- `/workbook_export <teacher_workspace_id>` — экспорт workbook;
- workbook import работает загрузкой `.xlsx` с caption `/workbook_import <teacher_workspace_id>`;
- bot-facing text должен идти через централизованный i18n layer;
- Telegram command names/descriptions должны проходить через `englishbot/command_registry.py`.

### Target behavior

- Telegram остаётся thin orchestration layer;
- текущие команды могут меняться, но не должны размывать архитектурные границы.

---

## 17. Архитектурные ограничения

Запрещено:

- смешивать бизнес-логику и Telegram handlers;
- использовать JSON как runtime source;
- делать implicit выбор workspace как общую норму;
- создавать скрытые зависимости между workspace;
- обходить publish boundary прямым использованием teacher content в student runtime;
- превращать workbook import/export в обязательный live sync слой.

### Current behavior

- ограничения в целом уже соблюдаются;
- текущие осознанные исключения узкие:
  - есть deterministic default authoring workspace для compatibility;
  - `/learn` fallback ещё использует этот дефолтный контент;
  - workspace UI/select flow пока отсутствует.

---

## 18. Optional подсистемы

- AI
- генерация изображений
- TTS
- Web App

### Current behavior

- ни одна из этих подсистем не является обязательной для core runtime;
- текущий продукт должен работать без них.

### Инвариант

> Core работает без optional подсистем.

---

## 19. Требования к разработке

Каждая новая фича должна:

- учитывать workspace ownership;
- использовать publish там, где контент переходит между workspace;
- не ломать snapshot;
- не вводить скрытые зависимости;
- иметь тесты;
- не добавлять новый bot-facing text мимо i18n;
- не добавлять новые Telegram commands мимо command registry;
- сохранять изменения минимальными и локальными.

---

## 20. Текущие ограничения

На текущем этапе система намеренно узкая.

### Current behavior

- нет content versioning;
- нет diff-based publish;
- нет back-sync из student workspace в teacher workspace;
- нет Google Sheets API;
- workbook support остаётся local-file based;
- workbook import пока использует simple validation/matching rules вместо полноценного diff/merge identity layer;
- нет workspace UI;
- нет полноценного workspace selection flow;
- нет сложной access-control hierarchy;
- нет развитой статистики beyond minimal per-session counters.

### Target behavior

- дальнейшее развитие возможно, но только поверх уже зафиксированных инвариантов:
  - workspace ownership
  - publish boundary
  - snapshot stability
  - SQLite as runtime source of truth

---

## 21. Главный принцип

> Система должна двигаться к workspace-first модели, а не обратно.
