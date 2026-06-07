Сделай в текущем репозитории EnglishBot узкий family-first export/deploy slice: оставь в SQLite исходный remote `source_url` картинки только как traceability metadata, но в exported family workbook подставляй в display-only колонку `image` не исходный URL скачивания, а текущий публичный URL локального runtime asset через nginx static base.

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

Подними только нужный контекст по module map:

* `englishbot/workbook_export.py`
* `englishbot/config.py`
* `englishbot/bootstrap.py`, only if startup env loading changes
* `docker-compose.yml`, only if runtime env injection is needed
* focused tests:
  * `tests/test_workbook_export.py`
  * `tests/test_bootstrap.py`, only if env loading changes

Контекст:

- сейчас family workbook export уже пишет `image_ref` и display-only `image`
- `image_ref` должен оставаться source of truth ссылкой на локальный runtime asset path
- `image` должен оставаться derived display-only колонкой для spreadsheet preview
- исходный remote `source_url` полезно хранить в SQLite, чтобы помнить, откуда был скачан оригинал
- но в exported `.xlsx` preview картинки должен открывать текущий публичный адрес файла на текущем сервере
- infra deployment already creates a host-managed env file with values like:
  - `INFRA_PUBLIC_BASE_URL`
  - `INFRA_STATIC_BASE_URL`
- on the server that file lives at `/srv/services/englishbot/infra-runtime.env`
- static runtime assets are served from nginx through the service-specific static URL

Главная цель:

- сохранить `source_url` в базе только как metadata
- при export строить display `image` formula через `INFRA_STATIC_BASE_URL`
- не ломать local/source-of-truth asset model
- не превращать это в redesign workbook import/export

Что именно нужно сделать:

1. Runtime access to infra env

- приложение во время runtime должно видеть значения из `infra-runtime.env`
- выбери минимальный надежный способ:
  - direct app startup path должен уметь подхватывать этот env file, если он существует
  - docker compose runtime тоже должен получать этот env file в environment контейнера
- не делай startup hard-fail, если файла нет в local dev

2. Narrow config helper

- добавь компактный helper для `INFRA_STATIC_BASE_URL`
- helper должен:
  - брать значение из environment
  - trim whitespace
  - убирать trailing slash
  - возвращать `None`, если значения нет

3. Workbook export URL policy

- в `englishbot/workbook_export.py` оставь `image_ref` без изменений
- display-only formula `image` должна строиться так:
  - если linked image points to a local runtime asset path under app assets, use `INFRA_STATIC_BASE_URL + public relative path`
  - если static base URL недоступен, безопасно fallback на текущее поведение
  - если usable public URL все равно не получается, оставь `image` пустым
- оригинальный `source_url` больше не должен быть first-choice export URL, когда есть локальный runtime asset plus static base

4. Public path rules

- поддержи текущие локальные формы ref minimally:
  - `assets/...`
  - `/app/assets/...`
- из них должен получаться public path relative to static root, например:
  - `assets/images/apple.jpg` -> `images/apple.jpg`
  - `/app/assets/images/apple.jpg` -> `images/apple.jpg`
- URL assembly должна быть аккуратной и deterministic

5. Scope discipline

Не делай в этой итерации:

- changes to workbook import semantics
- new DB schema
- asset backfill
- redesign of nginx/static infra
- runtime network calls during export

6. Tests

Добавь focused tests минимум для:

- export still keeps `image_ref` unchanged
- when `INFRA_STATIC_BASE_URL` is set and image ref is local, workbook `image` formula uses the current static public URL
- env loading picks up optional `infra-runtime.env` without breaking normal `.env` loading
- no startup hard dependency appears when infra file is absent

7. Documentation updates

Обнови:

* `CHANGELOG.md`
* `context/current-state.md`
* `.env.example`, if the env contract exposed to operators/devs changed

Current state should clearly say:

- workbook export now prefers `INFRA_STATIC_BASE_URL` for display-only image preview URLs
- `image_ref` remains the runtime source of truth
- original remote `source_url` remains only traceability metadata
- the running app can read `/srv/services/englishbot/infra-runtime.env` on deployed servers

Ожидаемый итог:

- экспортированный workbook показывает картинки по текущему nginx static URL сервера
- база продолжает помнить исходный remote URL отдельно
- локальный runtime asset model не ломается
- local dev без infra env file продолжает работать fail-closed
