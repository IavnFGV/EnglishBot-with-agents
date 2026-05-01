Сделай минимальное, но полное изменение в EnglishBot, чтобы правило хранения медиа стало таким:

- В SQLite и на сервере все runtime-медиа должны храниться локально.
- Если teacher при редактировании `image_ref` или `audio_ref` присылает внешний `http/https` URL, это допустимо только как входной формат: файл нужно скачать, положить в локальное хранилище под `data/assets/...`, а в runtime использовать локальный путь.
- При workbook import внешние ссылки на картинку или аудио тоже нужно скачивать локально до записи runtime-данных.
- Оригинальный внешний URL можно сохранить в asset metadata для трассировки, например в `source_url`, но он не должен оставаться единственным источником данных.
- `local_path` должен быть заполнен для используемых runtime asset rows.

Работай по правилам репозитория из `AGENTS.md`:

- Сначала держи изменение как можно уже.
- Читай только нужные файлы по `docs/module-map.md`.
- Не расширяй архитектуру без необходимости.
- После изменений обнови `CHANGELOG.md` и `context/current-state.md`.

Ожидаемый scope:

- Проверь и поправь `englishbot/assets.py`, чтобы появился единый helper для скачивания remote asset URL в локальный файл под `data/assets/...`.
- Проверь `englishbot/teacher_content.py` и teacher-content flow так, чтобы URL для `image_ref` и `audio_ref` локализовывались перед записью, а в asset row сохранялись `local_path` и при необходимости `source_url`.
- Проверь `englishbot/vocabulary.py`, чтобы прямые доменные вызовы вроде `create_learning_item(..., image_ref=<url>, audio_ref=<url>)` тоже соблюдали это правило, а не только Telegram UI.
- Проверь `englishbot/workbook_import.py`, чтобы workbook media download сохранял локальный файл и чтобы импортированные asset rows имели рабочий `local_path`; исходный URL можно оставить в `source_url`.
- Если в Telegram dialog уже есть отдельная логика скачивания image URL, убери дублирование и оставь одну доменную точку правды.

Тесты:

- Добавь или обнови только узкие тесты в релевантных файлах.
- Обязательно покрой:
  - teacher image/audio URL edit -> локальный `local_path` + сохранённый `source_url`
  - direct vocabulary create/update с remote media
  - workbook import с remote media
- Прогони только релевантные тесты, а не весь suite, если это не нужно.

Важно:

- Не ломай уже существующее поведение для локальных путей.
- Не делай внешний URL обязательным.
- Не храни runtime-медиа только как URL.
- Сохрани решение минимальным и совместимым с текущим asset registry.
