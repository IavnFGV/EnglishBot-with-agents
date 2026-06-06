Сделай в текущем репозитории EnglishBot следующий learner-TTS UI slice после базовой live-интеграции: переведи active `/learn` quiz flow на `aiogram-dialog` и встрои в learner quiz dialogs переиспользуемый TTS control block с двумя inline-кнопками `Listen` и `Voice`, чтобы переключение голоса было доступно прямо на каждом слове и одна и та же встраиваемая логика работала и в обычном `learn`, и в homework-backed quiz flow.


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
* chain_of_commands/058-internal-tts-service-integration.md

Контекст:

- предыдущая TTS итерация уже дала:
  - optional internal TTS client
  - `Listen` action в learner runtime
  - persisted user-selected `voice_id`
  - fail-closed live TTS request path
- сейчас выбор голоса доступен централизованно через settings, но этого недостаточно:
  - отдельный voice может плохо произносить конкретное слово
  - learner должен иметь возможность тут же на текущей quiz card переключить voice и сразу заново послушать
- current `learn` flow по-прежнему реализован через обычные aiogram handlers, а не через `aiogram-dialog`
- homework learner flow уже использует dialog-based surfaces
- эта задача нужна не только ради TTS UX, но и ради нормальной встраиваемости общего learner control block в двух местах

Работай строго по правилам репозитория из `AGENTS.md`:

- не расширяй scope на старые workspace/publish surfaces
- читай только task-specific файлы по `docs/module-map.md`
- все bot-facing тексты только через `englishbot/i18n.py`
- optional extras must not become required for core runtime
- новые или измененные команды проходят через `englishbot/command_registry.py`
- после завершения обнови `CHANGELOG.md`, `context/current-state.md` и `.env.example`, если появятся env changes
- держи `context/current-state.md` коротким

Перед реализацией подними только нужный контекст:

- learner/training slice:
  - `englishbot/training.py`
  - `englishbot/training_handlers.py`
  - `englishbot/homework.py`
  - `englishbot/homework_dialog.py`
  - `englishbot/learner_homework.py`, only if current homework learner dialog state depends on it
- runtime wiring slice:
  - `englishbot/bot.py`
  - `englishbot/runtime.py`
  - any current dialog registration or getter helpers directly used by learner flows
- TTS slice:
  - `englishbot/tts.py`
  - `englishbot/user_profiles.py`
  - `englishbot/settings_handlers.py`, only to avoid duplicating voice-resolution logic
- focused tests:
  - `tests/test_training_handlers.py`
  - `tests/test_homework_dialog.py`
  - `tests/test_learner_homework.py`
  - `tests/test_training.py`, only if session/domain shape changes
  - any focused dialog tests closest to the final learner quiz surfaces

Главная цель:

- сделать `Listen` и `Voice` встроенной частью learner quiz UI
- дать learner возможность быстро менять голос на конкретном слове
- переиспользовать один и тот же learner TTS control block в `learn` и homework-backed quiz
- перестать держать `learn` на custom handler-only path, если это мешает clean reusable UI composition

Приоритет этой итерации:

1. перевести active `/learn` quiz flow на `aiogram-dialog`
2. встроить `Listen + Voice` как reusable dialog controls
3. переиспользовать те же controls в homework quiz UI
4. сохранить fail-closed TTS behavior
5. не разнести learner runtime на две несогласованные UI архитектуры

Что именно нужно реализовать:

1. Move `learn` learner quiz UI to `aiogram-dialog`

- active `/learn` quiz surface должен стать dialog-based
- не нужно переписывать business logic из `training.py` в dialog layer
- domain rules, answer progression, session persistence и staged exercise state должны остаться в focused domain modules
- `aiogram-dialog` слой должен:
  - читать current question/session snapshot
  - рендерить current learner screen
  - маршрутизировать answer actions back into existing domain logic
- переход на dialog нужен потому, что дальше learner controls должны встраиваться переиспользуемо, а не поддерживаться отдельным кастомным способом только для `learn`

2. Reusable learner TTS control block

- вынеси `Listen` и `Voice` в компактный reusable UI/control slice
- это должен быть именно встраиваемый learner quiz block, а не settings-only flow
- block должен быть пригоден как минимум для:
  - `learn` quiz dialog
  - homework-backed learner quiz dialog
- block должен инкапсулировать:
  - кнопку `Listen`
  - кнопку `Voice`
  - resolve effective voice
  - compact voice chooser presentation for the current learner
- если нужны small helper modules/functions for dialog getter/builders/callback handlers, делай их локально и понятно

3. Per-word voice switching UX

- на каждой learner quiz card должны быть две отдельные inline buttons:
  - `Listen`
  - `Voice`
- ожидание UX:
  - learner нажимает `Listen` и слушает текущее слово
  - learner слышит, что этот voice плохо произносит слово
  - learner нажимает `Voice`
  - быстро выбирает другой voice
  - тут же снова жмёт `Listen`
- это не отменяет глобально сохранённый user preference:
  - выбор на quiz card должен обновлять persisted user `tts_voice_id`
  - следующий listen должен уже идти через новый selected voice
- показывай текущий selected voice в chooser clearly and compactly

4. Voice chooser inside learner dialogs

- `Voice` button должна открывать компактный learner-facing chooser без ухода в отдельную общую settings architecture
- chooser должен быть естественной частью learner dialog flow
- допустимый UX:
  - отдельное dialog state/window внутри learner flow
  - или компактная overlay-like dialog screen if that matches current patterns
- but:
  - не ломай answer session state
  - не теряй current training question
  - после выбора learner должен легко вернуться к тому же quiz screen
- chooser должен переиспользовать текущую TTS `/voices` модель и persisted user preference

5. Shared behavior across `learn` and homework

- один и тот же learner TTS control block должен использоваться в:
  - plain `/learn`
  - homework-backed quiz runtime
- если topic-launched training автоматически использует тот же active learner quiz surface, это хороший бонус
- не делай две независимые реализации с копипастой
- если для этого нужен единый learner quiz dialog shell поверх existing `training.py`, это acceptable and likely preferred

6. Runtime behavior

- `Listen` в dialog должен:
  - определить current English text for the active item
  - определить effective voice
  - вызвать existing TTS client
  - отправить learner audio
- current fail-closed behavior нужно сохранить:
  - если TTS unavailable, quiz не ломается
  - если Telegram reject'ит voice/audio, quiz не ломается
  - learner получает мягкое localized message
- если в прошлой итерации TTS message уже стал частью learner screen lifecycle, сохрани это поведение и после dialog migration:
  - stale pronunciation message не должен захламлять chat

7. Modularization expectations

- цель этой итерации не просто “добавить еще одну кнопку”
- цель — выделить reusable learner-level TTS UI/control seam
- модульность должна быть достаточной, чтобы:
  - не дублировать code between `learn` and homework
  - не размазывать TTS-specific callback parsing по нескольким несогласованным handlers
- при этом не нужно строить большой generic widget framework ради одного feature
- минимальный acceptable shape:
  - focused learner dialog helper(s)
  - focused TTS control builder/getter/callback glue
  - сохранение domain logic в `training.py`

8. Scope discipline

Минимальный практический scope этой итерации:

- migrate active `/learn` learner quiz UI to `aiogram-dialog`
- reusable `Listen + Voice` learner control block
- voice chooser embedded into learner dialogs
- reuse same block in homework learner quiz flow
- persisted voice selection still works
- focused tests

Не делай в этой итерации:

- persistent synthesized-audio variant storage keyed by `learning_item` + `voice_id` + model
- broad TTS asset model redesign
- teacher-side TTS controls
- public TTS endpoint exposure
- large rewrite of unrelated teacher/homework authoring dialogs
- parallel second learner UI framework beside dialogs

9. Tests

Добавь focused tests минимум для:

- `/learn` quiz flow now renders through dialog-based learner screen without losing current staged-question behavior
- learner quiz screen in `learn` shows both `Listen` and `Voice`
- homework learner quiz screen shows the same TTS control block
- choosing a new voice inside the learner dialog persists the selected `tts_voice_id`
- after selecting a voice, `Listen` uses that new voice
- TTS failure inside dialog still fails closed without losing the active learner question
- current learner screen cleanup still removes stale pronunciation voice messages when moving to the next word or finishing

10. Documentation updates

Обнови:

- `CHANGELOG.md`
- `context/current-state.md`
- `docs/architecture.md`, only if learner runtime structure changed materially
- `.env.example`, only if env shape changed

Current state should clearly say:

- active `/learn` learner quiz UI is now dialog-based
- learner quiz dialogs expose `Listen` and per-word `Voice` switching inline
- the same learner TTS control block is reused across `learn` and homework learner quiz surfaces
- persisted user voice preference still exists, but voice can now be switched directly from the current word screen

Ожидаемый итог:

- learner может на каждом слове не только слушать pronunciation, но и мгновенно менять voice
- `Listen` и `Voice` становятся встроенным reusable learner control block
- один и тот же control block работает и в `learn`, и в homework quiz flow
- `learn` больше не висит на bespoke non-dialog UI path, который мешает clean embedding
- следующую TTS storage итерацию можно будет делать уже поверх более чистого learner UI seam
