Сделай минимальное, но полное изменение в EnglishBot, чтобы связь учителей и учеников определялась только через `student` workspaces, без отдельной таблицы teacher-student links.

Работай по правилам репозитория из `AGENTS.md`:

- Сначала держи изменение как можно уже.
- Читай только нужные файлы по `docs/module-map.md`.
- Не расширяй архитектуру без необходимости.
- После изменений обнови `CHANGELOG.md` и `context/current-state.md`.

Целевая модель:

- `workspaces` и `workspace_members` остаются источником истины для доступа.
- `teacher` workspaces остаются authoring-пространствами.
- `student` workspaces становятся единственным источником истины для teacher-student grouping.
- Отдельная таблица `teacher_student_links` больше не нужна и должна быть удалена из runtime-схемы и доменной логики.
- Один ученик может состоять в нескольких `student` workspaces с разными учителями.

Ожидаемый scope:

- Проверь и поправь `englishbot/db.py`, чтобы bootstrap/migrations больше не создавали `teacher_student_links`, а legacy-таблица удалялась.
- Проверь `englishbot/workspaces.py`:
  - shared teacher-student lookup должен опираться только на `workspace_members`
  - добавь helper для списка общих student workspaces между teacher и student
  - добавь helper для списка учеников teacher на основе membership в `student` workspaces
  - `get_or_create_student_workspace(...)` должен продолжать работать без старой link-таблицы
- Проверь `englishbot/teacher_student.py`, чтобы:
  - `/invite` и `/join` продолжали работать
  - `join` больше не создавал teacher-student link row
  - ограничение “student already linked” было удалено
- Проверь `englishbot/homework.py`, `englishbot/topic_access.py`, `englishbot/teacher_assignments.py` и связанные handler/domain flow:
  - не должно остаться зависимости от `teacher_student_links`
  - recipients для assignment UI должны строиться из membership в `student` workspaces
  - старые direct commands вроде `/assign <student_user_id> ...` и `/granttopic <student_user_id> ...` могут оставаться fail-closed, если для пары teacher-student больше одного общего `student` workspace
- Не добавляй новый admin UI в этом шаге; меняем только модель и совместимый доменный слой.

Тесты:

- Обнови только релевантные тесты.
- Обязательно покрой:
  - `join` создаёт или находит shared student workspace без отдельной link-таблицы
  - student может join к двум разным teachers
  - assignment/topic-access/homework flows продолжают работать через student workspace membership
  - recipient listing для teacher assignment flow больше не зависит от старой таблицы
- Прогони только релевантные тесты, а не весь suite, если это не нужно.

Важно:

- Удаляй старую one-to-one teacher-student модель без сохранения legacy-обвязки, если она больше не нужна.
- Не ломай authoring/publish/training boundaries.
- Не вводи новую сущность поверх workspaces в этом change set.
- Оставь решение минимальным и чистым по исходникам.
