'use strict';

const app = document.getElementById('app');
const webApp = window.Telegram?.WebApp;
const initData = webApp?.initData || '';
const MAX_UPLOAD_SIDE = 1600;
const MAX_UPLOAD_BYTES = 900 * 1024;

let labels = {};
let languages = [];
let heroineEnabled = false;
let backHandler = null;
const imageCache = new Map();

function syncTheme() {
  if (webApp?.colorScheme) document.documentElement.dataset.theme = webApp.colorScheme;
}

webApp?.ready();
webApp?.expand();
syncTheme();
webApp?.onEvent?.('themeChanged', syncTheme);
webApp?.BackButton?.onClick(() => backHandler && backHandler());

function t(key, values = {}) {
  let text = labels[key] || key;
  for (const [name, value] of Object.entries(values)) text = text.replace(`{${name}}`, value);
  return text;
}

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === 'class') node.className = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key === 'style' || key.startsWith('aria-')) node.setAttribute(key, value);
    else if (value !== undefined && value !== null) node[key] = value;
  }
  for (const child of children) if (child !== null && child !== undefined) node.append(child);
  return node;
}

// Native append() prints null as text, so drop empty optional nodes first.
const present = (...nodes) => nodes.filter((node) => node !== null && node !== undefined);

class ApiError extends Error {}

async function api(path, { method = 'GET', json, body, contentType } = {}) {
  const headers = { 'X-Telegram-Init-Data': initData };
  if (json !== undefined) { body = JSON.stringify(json); headers['Content-Type'] = 'application/json'; }
  if (contentType) headers['Content-Type'] = contentType;
  const response = await fetch(`/mini-app/api/editor${path}`, { method, headers, body, cache: 'no-store' });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new ApiError(payload.error || 'network_error');
  }
  return response;
}

const getJson = async (path) => (await api(path)).json();
const postJson = async (path, json = {}) => (await api(path, { method: 'POST', json })).json();

function errorText(error) {
  return error?.message === 'expired_init_data' ? t('expired') : t('error');
}

function setBack(handler) {
  backHandler = handler;
  if (handler) webApp?.BackButton?.show(); else webApp?.BackButton?.hide();
}

function screen(...children) {
  app.replaceChildren(...children.filter((child) => child !== null && child !== undefined));
  window.scrollTo(0, 0);
}

function fail(error) {
  screen(el('p', { class: 'status error' }, errorText(error)), el('button', { onclick: showTopics }, t('back')));
}

async function imageUrl(word) {
  if (!word.image_id) return null;
  if (!imageCache.has(word.image_id)) {
    imageCache.set(word.image_id, api(`/words/${word.id}/image?v=${word.image_id}`)
      .then((response) => response.blob())
      .then((blob) => URL.createObjectURL(blob))
      .catch(() => { imageCache.delete(word.image_id); return null; }));
  }
  return imageCache.get(word.image_id);
}

function fillImage(img, word) {
  imageUrl(word).then((url) => { if (url) img.src = url; });
}

// Topics

async function showTopics() {
  setBack(null);
  let data;
  try { data = await getJson('/topics'); } catch (error) { app.replaceChildren(el('p', { class: 'status error' }, errorText(error))); return; }
  labels = data.labels || labels;
  languages = data.languages || languages;
  heroineEnabled = Boolean(data.heroine);
  document.title = t('title');
  const list = el('div', { class: 'list' });
  for (const topic of data.topics) {
    list.append(el('button', { class: 'item', onclick: () => showWords(topic.id) },
      el('span', { class: 'texts' },
        el('span', { class: 'title' }, topic.title),
        el('span', { class: 'sub' }, t('word_count', { count: topic.word_count })))));
  }
  screen(
    el('h1', {}, t('title')),
    el('button', { onclick: () => askTopicTitle('', async (title) => showWords((await postJson('/topics', { title })).id)) }, t('new_topic')),
    el('button', { class: 'secondary', onclick: showHomework }, t('homework_list')),
    el('button', { class: 'secondary', onclick: showSets }, t('sets')),
    data.heroine ? el('button', { class: 'secondary', onclick: showPictures }, heroineButtonText(data.heroine)) : null,
    data.is_owner ? el('button', { class: 'secondary', onclick: () => showModels() }, t('models')) : null,
    data.topics.length ? list : el('p', { class: 'muted' }, t('no_topics')),
  );
}

function askTopicTitle(initial, onSubmit, caption = t('topic_title')) {
  const previousBack = backHandler;
  const input = el('input', { type: 'text', value: initial, maxLength: 200, placeholder: caption });
  const status = el('p', { class: 'status' });
  const submit = async () => {
    if (!input.value.trim()) { input.focus(); return; }
    try { await onSubmit(input.value.trim()); } catch (error) { status.className = 'status error'; status.textContent = errorText(error); }
  };
  input.addEventListener('keydown', (event) => { if (event.key === 'Enter') submit(); });
  setBack(previousBack || showTopics);
  screen(
    el('label', {}, caption, input),
    el('div', { class: 'row' },
      el('button', { class: 'secondary grow', onclick: previousBack || showTopics }, t('cancel')),
      el('button', { class: 'grow', onclick: submit }, t('save'))),
    status,
  );
  input.focus();
}

// Words of one topic

async function showWords(topicId, filter = '') {
  setBack(showTopics);
  let data;
  try { data = await getJson(`/topics/${topicId}/words`); } catch (error) { fail(error); return; }
  const { topic, words } = data;
  const list = el('div', { class: 'list' });
  const search = el('input', { type: 'search', value: filter, placeholder: t('search') });
  const renderList = () => {
    const query = search.value.trim().toLowerCase();
    const visible = words.filter((word) => !query
      || word.text.toLowerCase().includes(query)
      || Object.values(word.translations).some((value) => value.toLowerCase().includes(query)));
    list.replaceChildren(...visible.map((word) => {
      const thumb = el('img', { class: 'thumb', alt: '', loading: 'lazy' });
      fillImage(thumb, word);
      const translation = Object.values(word.translations).find(Boolean) || '';
      return el('button', { class: 'item', onclick: () => showWord(topic, word) },
        thumb,
        el('span', { class: 'texts' },
          el('span', { class: 'title' }, wordTitle(word)),
          el('span', { class: 'sub' }, translation)));
    }));
    list.hidden = visible.length === 0;
  };
  search.addEventListener('input', renderList);
  renderList();
  screen(
    el('h1', {}, topic.title),
    el('div', { class: 'row' },
      el('button', { class: 'grow', onclick: () => showWord(topic, null) }, t('new_word')),
      el('button', { class: 'secondary', onclick: () => askTopicTitle(topic.title, async (title) => {
        await postJson(`/topics/${topic.id}`, { title });
        showWords(topic.id);
      }) }, t('rename'))),
    words.length > 8 ? search : null,
    words.length ? list : el('p', { class: 'muted' }, t('no_words')),
    el('div', { class: 'spacer' }),
    el('button', { class: 'danger', onclick: () => confirmThen(t('delete_topic_confirm'), async () => {
      await postJson(`/topics/${topic.id}/delete`);
      showTopics();
    }) }, t('delete_topic')),
  );
}

function confirmThen(message, action) {
  const run = () => action().catch(fail);
  if (webApp?.showConfirm) webApp.showConfirm(message, (ok) => { if (ok) run(); });
  else if (window.confirm(message)) run();
}

// One word

function showWord(topic, word, savedMessage = false) {
  setBack(() => showWords(topic.id));
  const status = el('p', { class: 'status' });
  const setStatus = (text, kind = '') => { status.className = `status ${kind}`; status.textContent = text; };
  const textInput = el('input', { type: 'text', value: word?.text || '', maxLength: 200, autocapitalize: 'off' });
  const [mainLanguage, ...otherLanguages] = languages;
  const translationInputs = {};
  const translationField = (language, caption) => {
    const input = el('input', { type: 'text', value: word?.translations?.[language.code] || '', maxLength: 200 });
    translationInputs[language.code] = input;
    return el('label', {}, caption, input);
  };
  const mainField = mainLanguage ? translationField(mainLanguage, `${t('translation')} (${mainLanguage.label})`) : null;
  const others = otherLanguages.map((language) => translationField(language, language.label));
  const othersFilled = otherLanguages.some((language) => word?.translations?.[language.code]);
  // An irregular verb shows its forms from the bot's list; its English text is not edited here.
  const isVerb = word?.type === 'verb';
  textInput.disabled = isVerb;
  const verbInfo = isVerb ? el('span', { class: 'sub' }, `${wordTitle(word)} · ${t('verb_from_list')}`) : null;

  const save = async () => {
    if (!textInput.value.trim()) { textInput.focus(); return; }
    const payload = {
      translations: Object.fromEntries(Object.entries(translationInputs).map(([code, input]) => [code, input.value])),
    };
    if (!isVerb) payload.text = textInput.value;
    saveButton.disabled = true;
    try {
      const saved = word
        ? await postJson(`/words/${word.id}`, payload)
        : await postJson(`/topics/${topic.id}/words`, payload);
      const isNew = !word;
      word = saved;
      if (isNew) { showWord(topic, saved, true); return; }
      setStatus(t('saved'), 'ok');
    } catch (error) {
      setStatus(errorText(error), 'error');
    } finally { saveButton.disabled = false; }
  };
  const saveButton = el('button', { onclick: save }, t('save'));
  [textInput, ...Object.values(translationInputs)].forEach((input) => input.addEventListener('keydown', (event) => { if (event.key === 'Enter') save(); }));

  screen(
    el('label', {}, t('word'), textInput),
    verbInfo,
    mainField,
    others.length ? el('details', { open: othersFilled }, el('summary', {}, t('other_languages')), ...others) : null,
    saveButton,
    status,
    word ? pictureSection(word, (updated) => { word = updated; }, setStatus) : null,
    word ? el('div', { class: 'spacer' }) : null,
    word ? el('button', { class: 'danger', onclick: () => confirmThen(t('delete_word_confirm'), async () => {
      await postJson(`/words/${word.id}/delete`);
      showWords(topic.id);
    }) }, t('delete_word')) : null,
  );
  if (!word) textInput.focus();
  if (savedMessage) setStatus(t('saved'), 'ok');
}

function pictureSection(word, onChange, setStatus) {
  const section = el('div', { class: 'section' });
  const render = () => {
    const preview = word.image_id
      ? el('img', { class: 'picture', alt: '' })
      : el('div', { class: 'picture empty' }, t('photo'));
    if (word.image_id) fillImage(preview, word);
    const fileInput = el('input', { type: 'file', accept: 'image/*', hidden: true });
    fileInput.addEventListener('change', async () => {
      const file = fileInput.files?.[0];
      if (!file) return;
      await update(async () => {
        const blob = await shrinkImage(file);
        return (await api(`/words/${word.id}/image`, { method: 'POST', body: blob, contentType: blob.type || 'application/octet-stream' })).json();
      });
    });
    const urlInput = el('input', { type: 'url', placeholder: t('photo_url'), inputMode: 'url' });
    const useUrl = () => urlInput.value.trim() && update(() => postJson(`/words/${word.id}/image-url`, { url: urlInput.value.trim() }));
    urlInput.addEventListener('keydown', (event) => { if (event.key === 'Enter') useUrl(); });
    section.replaceChildren(...present(
      el('strong', {}, t('photo')),
      preview,
      fileInput,
      el('button', { class: 'secondary', onclick: () => fileInput.click() }, t('choose_photo')),
      urlInput,
      el('button', { class: 'secondary', onclick: useUrl }, t('use_url')),
      word.image_id ? el('button', { class: 'link', onclick: () => update(() => postJson(`/words/${word.id}/image/delete`)) }, t('remove_photo')) : null,
      heroineEnabled ? heroineRequest(word, setStatus) : null,
    ));
  };
  const update = async (request) => {
    setStatus(t('uploading'));
    section.querySelectorAll('button').forEach((button) => { button.disabled = true; });
    try {
      word = await request();
      onChange(word);
      setStatus(t('saved'), 'ok');
    } catch (error) {
      setStatus(errorText(error), 'error');
    }
    render();
  };
  render();
  return section;
}

// Heroine pictures drawn by the optional artist container

const HEROINE_POLL_MS = 8000;

function heroineButtonText(counts) {
  const parts = [];
  if (counts.drawing) parts.push(`🖌 ${t('heroine_count_drawing', { count: counts.drawing })}`);
  if (counts.open) parts.push(t('heroine_count_ready', { count: counts.open }));
  return parts.length ? `${t('heroine_pictures')} · ${parts.join(' · ')}` : t('heroine_pictures');
}

// Shows whether the artist is drawing this word and re-checks until it is done.
function heroineProgress(wordId) {
  const line = el('div', {});
  const check = async () => {
    if (!line.isConnected && line.dataset.started) return;
    line.dataset.started = '1';
    let picture = null;
    try { picture = (await getJson('/heroine')).pictures.find((item) => item.word_id === wordId) || null; } catch { return; }
    if (picture?.status === 'queued') {
      line.replaceChildren(el('p', { class: 'status drawing' }, `🖌 ${t('heroine_drawing')}`));
      setTimeout(check, HEROINE_POLL_MS);
    } else if (picture) {
      line.replaceChildren(el('button', { class: 'link', onclick: showPictures }, picture.status === 'ready' ? t('heroine_ready_open') : t('heroine_failed', { error: picture.error || '' })));
    } else {
      line.replaceChildren();
    }
  };
  return { line, check };
}

function heroineRequest(word, setStatus) {
  const progress = heroineProgress(word.id);
  const idea = el('textarea', { rows: 2, maxLength: 500, placeholder: t('heroine_idea_hint') });
  const button = el('button', { class: 'secondary', onclick: async () => {
    button.disabled = true;
    try {
      await postJson(`/words/${word.id}/heroine`, { scene: idea.value });
      idea.value = '';
      setStatus(t('heroine_requested'), 'ok');
      progress.check();
    } catch (error) { setStatus(errorText(error), 'error'); } finally { button.disabled = false; }
  } }, t('heroine_draw'));
  setTimeout(progress.check, 0);
  return el('div', { class: 'section' }, progress.line,
    el('details', {}, el('summary', {}, t('heroine_draw')), el('label', {}, t('heroine_idea'), idea), button));
}

async function showPictures() {
  setBack(showTopics);
  let data;
  try { data = await getJson('/heroine'); } catch (error) { fail(error); return; }
  labels = data.labels || labels;
  const worker = ['offline', 'auth_required', 'limited'].includes(data.worker)
    ? el('p', { class: 'status error' }, t(`heroine_state_${data.worker}`)) : null;
  const cards = data.pictures.map((picture) => {
    const status = el('p', { class: 'status' });
    const act = async (path, json) => {
      card.querySelectorAll('button').forEach((button) => { button.disabled = true; });
      try { await postJson(`/heroine/${picture.id}/${path}`, json); showPictures(); }
      catch (error) { status.className = 'status error'; status.textContent = errorText(error); card.querySelectorAll('button').forEach((button) => { button.disabled = false; }); }
    };
    const scene = el('textarea', { rows: 3, maxLength: 500, value: picture.scene || picture.scene_request || '' });
    let body;
    if (picture.status === 'ready') {
      const img = el('img', { class: 'picture', alt: picture.word });
      api(`/heroine/${picture.id}/image`).then((response) => response.blob()).then((blob) => { img.src = URL.createObjectURL(blob); }).catch(() => {});
      body = [img, el('button', { onclick: () => act('approve') }, t('heroine_use'))];
    } else if (picture.status === 'failed') {
      body = [el('p', { class: 'status error' }, t('heroine_failed', { error: picture.error || '' }))];
    } else {
      body = [el('p', { class: 'muted' }, picture.scene_request ? `${t('heroine_drawing')} ${picture.scene_request}` : t('heroine_drawing'))];
    }
    const card = el('div', { class: 'homework-card' },
      el('strong', {}, picture.word),
      ...body,
      ...(picture.status === 'queued' ? [] : [
        el('label', {}, t('heroine_scene'), scene),
        el('button', { class: 'secondary', onclick: () => act('redraw', { scene: scene.value }) }, t('heroine_redraw')),
      ]),
      el('button', { class: 'link', onclick: () => act('skip') }, t('heroine_skip')),
      status);
    return card;
  });
  const title = el('h1', {}, t('heroine_pictures'));
  // While something is being drawn, re-check quietly and redraw the screen only when a
  // picture changes state, so a scene being edited is not lost.
  const signature = (pictures) => pictures.map((picture) => `${picture.id}:${picture.status}`).join(',');
  const watch = async () => {
    if (!title.isConnected) return;
    try {
      const next = await getJson('/heroine');
      if (!title.isConnected) return;
      if (signature(next.pictures) !== signature(data.pictures) || next.worker !== data.worker) { showPictures(); return; }
    } catch { /* keep the current screen */ }
    setTimeout(watch, HEROINE_POLL_MS);
  };
  if (data.pictures.some((picture) => picture.status === 'queued')) setTimeout(watch, HEROINE_POLL_MS);
  screen(
    title,
    worker,
    cards.length ? el('div', { class: 'list' }, ...cards) : el('p', { class: 'muted' }, t('heroine_none')),
  );
}

// Large phone photos are scaled down before upload; the server re-encodes them anyway.
async function shrinkImage(file) {
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
    const scale = Math.min(1, MAX_UPLOAD_SIDE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    const context = canvas.getContext('2d');
    context.fillStyle = '#fff';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    // nginx accepts 1 MB bodies by default, so keep uploads below that.
    let blob = null;
    for (const quality of [0.9, 0.8, 0.7, 0.6, 0.5]) {
      blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality));
      if (blob && blob.size < MAX_UPLOAD_BYTES) break;
    }
    return blob || file;
  } catch {
    return file;
  }
}

// Free AI model queue (owner only)

const modelChecks = new Map();

function modelStatsText(stats) {
  if (!stats || (!stats.successes && !stats.failures)) return t('model_no_stats');
  const base = t('model_stats', { ok: stats.successes, fail: stats.failures });
  return stats.avg_seconds ? `${base} · ${t('model_avg_seconds', { seconds: stats.avg_seconds })}` : base;
}

async function showModels(state = null) {
  setBack(showTopics);
  if (!state) {
    try { state = await getJson('/models'); } catch (error) { fail(error); return; }
  }
  const queue = state.queue.map((model) => model.id);
  const saveQueue = async (next) => {
    try { showModels(await postJson('/models', { queue: next })); } catch (error) { fail(error); }
  };
  const move = (index, delta) => {
    const next = [...queue];
    const [model] = next.splice(index, 1);
    next.splice(index + delta, 0, model);
    saveQueue(next);
  };
  const checkLine = (modelId) => {
    const line = el('span', { class: 'sub' });
    const result = modelChecks.get(modelId);
    if (result === 'running') line.textContent = t('model_testing');
    else if (result?.ok) line.textContent = t('model_test_ok', { found: result.found, expected: result.expected, seconds: result.seconds });
    else if (result) line.textContent = t('model_test_failed', { error: result.error });
    return line;
  };
  const runCheck = async (modelId) => {
    modelChecks.set(modelId, 'running');
    showModels(state);
    try { modelChecks.set(modelId, await postJson('/models/test', { model: modelId })); } catch (error) { modelChecks.set(modelId, { ok: false, error: error.message }); }
    showModels(); // reload so the stats include this check
  };
  const card = (model, buttons) => el('div', { class: 'model-card' },
    el('span', { class: 'title' }, model.name),
    el('span', { class: 'sub mono' }, model.id),
    el('span', { class: 'sub' }, model.free_now === false ? `⚠️ ${t('model_not_free')}` : modelStatsText(model.stats)),
    checkLine(model.id),
    el('div', { class: 'model-actions' }, ...buttons));
  const queueCards = state.queue.map((model, index) => card(model, [
    el('button', { class: 'secondary', disabled: index === 0, onclick: () => move(index, -1) }, '↑'),
    el('button', { class: 'secondary', disabled: index === state.queue.length - 1, onclick: () => move(index, 1) }, '↓'),
    el('button', { class: 'secondary', onclick: () => runCheck(model.id) }, t('model_test')),
    el('button', { class: 'secondary', onclick: () => saveQueue(queue.filter((id) => id !== model.id)) }, t('model_remove')),
  ]));
  const availableCards = state.available.map((model) => card(model, [
    el('button', { onclick: () => saveQueue([...queue, model.id]) }, t('model_add')),
    el('button', { class: 'secondary', onclick: () => runCheck(model.id) }, t('model_test')),
  ]));
  screen(
    el('h1', {}, t('models')),
    el('p', { class: 'muted' }, t('models_hint')),
    state.configured ? null : el('p', { class: 'status error' }, t('models_not_configured')),
    state.catalog_error ? el('p', { class: 'status error' }, t('models_catalog_error')) : null,
    el('strong', {}, t('models_queue')),
    queueCards.length ? el('div', { class: 'list' }, ...queueCards) : el('p', { class: 'status error' }, t('models_empty_queue')),
    availableCards.length ? el('strong', {}, t('models_available')) : null,
    availableCards.length ? el('div', { class: 'list' }, ...availableCards) : null,
  );
}

// Saved homework sets: rename and assign again

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString();
}

const SETS_PAGE = 10;

// One-of-few choice as a row of the app's buttons (no native select); node.value reads and sets the choice.
function choiceGroup(options, initial = options[0]?.value) {
  const node = el('div', { class: 'choices', role: 'radiogroup' });
  const buttons = options.map((option) => el('button', { class: 'choice', type: 'button', role: 'radio', onclick: () => select(option.value) }, option.label));
  let current = null;
  const select = (value) => {
    current = value;
    buttons.forEach((button, index) => {
      const on = options[index].value === value;
      button.classList.toggle('selected', on);
      button.setAttribute('aria-checked', String(on));
    });
  };
  Object.defineProperty(node, 'value', { get: () => current, set: select });
  node.has = (value) => options.some((option) => option.value === value);
  node.append(...buttons);
  select(initial);
  return node;
}

function field(caption, control) {
  return el('div', { class: 'field' }, el('span', { class: 'field-caption' }, caption), control);
}

function applyDefaults(defaults, recipient, mode) {
  if (defaults?.recipient && recipient.has(String(defaults.recipient))) recipient.value = String(defaults.recipient);
  if (defaults?.mode && mode.has(defaults.mode)) mode.value = defaults.mode;
}

async function showSets() {
  setBack(showTopics);
  let data;
  try { data = await getJson('/sets'); } catch (error) { fail(error); return; }
  labels = data.labels || labels;
  const setItem = (set) => el('button', { class: 'item', onclick: () => showSet(set.id) },
    el('span', { class: 'texts' },
      el('span', { class: 'title' }, set.title),
      el('span', { class: 'sub' }, `${formatDate(set.saved_at)} · ${t('word_count', { count: set.item_count })}`)));
  const drafts = (data.drafts || []).map((draft) => el('button', { class: 'item', onclick: () => showDraft(draft.id, showSets) },
    el('span', { class: 'texts' },
      el('span', { class: 'title' }, `📝 ${draft.title}`),
      el('span', { class: 'sub' }, `${formatDate(draft.updated_at)} · ${t('word_count', { count: draft.item_count })}`))));
  const inProgress = data.sets.filter((set) => set.active_count > 0);
  const others = data.sets.filter((set) => set.active_count === 0);
  // Older sets stay reachable through paging and search instead of one endless list.
  let shown = SETS_PAGE;
  const othersList = el('div', { class: 'list' });
  const moreButton = el('button', { class: 'secondary' }, t('show_more'));
  const search = el('input', { type: 'search', placeholder: t('search_sets') });
  const renderOthers = () => {
    const query = search.value.trim().toLowerCase();
    const matching = query ? others.filter((set) => set.title.toLowerCase().includes(query)) : others;
    othersList.replaceChildren(...matching.slice(0, shown).map(setItem));
    othersList.hidden = matching.length === 0;
    moreButton.hidden = matching.length <= shown;
  };
  moreButton.addEventListener('click', () => { shown += SETS_PAGE; renderOthers(); });
  search.addEventListener('input', () => { shown = SETS_PAGE; renderOthers(); });
  renderOthers();
  screen(
    el('h1', {}, t('sets')),
    el('button', { onclick: createHomework }, t('new_homework')),
    drafts.length ? el('strong', {}, t('drafts')) : null,
    drafts.length ? el('div', { class: 'list' }, ...drafts) : null,
    inProgress.length ? el('strong', {}, t('sets_in_progress')) : null,
    inProgress.length ? el('div', { class: 'list' }, ...inProgress.map(setItem)) : null,
    others.length && (drafts.length || inProgress.length) ? el('strong', {}, t('saved_sets')) : null,
    others.length > SETS_PAGE ? search : null,
    others.length ? othersList : null,
    others.length ? moreButton : null,
    data.sets.length || drafts.length ? null : el('p', { class: 'muted' }, t('no_sets')),
    data.archived_count ? el('button', { class: 'link', onclick: showArchive }, `${t('archive')} (${data.archived_count})`) : null,
  );
}

async function showArchive() {
  setBack(showSets);
  let data;
  try { data = await getJson('/sets/archive'); } catch (error) { fail(error); return; }
  const search = el('input', { type: 'search', placeholder: t('search_sets') });
  const list = el('div', { class: 'list' });
  const render = () => {
    const query = search.value.trim().toLowerCase();
    const matching = data.sets.filter((set) => !query || set.title.toLowerCase().includes(query));
    list.replaceChildren(...matching.map((set) => el('button', { class: 'item', onclick: () => showSet(set.id, '', showArchive) },
      el('span', { class: 'texts' },
        el('span', { class: 'title' }, set.title),
        el('span', { class: 'sub' }, `${formatDate(set.saved_at)} · ${t('word_count', { count: set.item_count })}`)))));
    list.hidden = matching.length === 0;
  };
  search.addEventListener('input', render);
  render();
  screen(el('h1', {}, t('archive')), data.sets.length > 10 ? search : null, list);
}

function statusLabel(status) {
  if (status === 'completed') return t('assignment_completed');
  if (status === 'cancelled') return t('homework_cancelled');
  return t('assignment_active');
}

// Add a word to a saved set: pick from the dictionary or create a new one

function showAddWord(setId, topics, backTo) {
  setBack(() => showSet(setId, '', backTo));
  const status = el('p', { class: 'status' });
  const add = async (payload) => {
    try {
      await postJson(`/sets/${setId}/words`, payload);
      showSet(setId, t('saved'), backTo);
    } catch (error) { status.className = 'status error'; status.textContent = errorText(error); }
  };
  const results = el('div', { class: 'list' });
  results.hidden = true;
  const search = el('input', { type: 'search', placeholder: t('search_dictionary'), autocapitalize: 'off' });
  let timer = null;
  search.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const query = search.value.trim();
      if (!query) { results.hidden = true; return; }
      try {
        const found = await postJson('/words/search', { q: query });
        results.replaceChildren(...found.words.map((word) => el('button', { class: 'item', onclick: () => add({ word_id: word.id }) },
          el('span', { class: 'texts' },
            el('span', { class: 'title' }, word.text),
            el('span', { class: 'sub' }, Object.values(word.translations).find(Boolean) || '')))));
        results.hidden = found.words.length === 0;
      } catch (error) { fail(error); }
    }, 250);
  });
  const topicList = el('datalist', { id: 'add-word-topics' }, ...topics.map((topic) => el('option', { value: topic.title })));
  const en = el('input', { type: 'text', maxLength: 100, placeholder: 'English', autocapitalize: 'off' });
  const ru = el('input', { type: 'text', maxLength: 200, placeholder: t('translation') });
  const topic = el('input', { type: 'text', maxLength: 100, placeholder: t('draft_topic') });
  topic.setAttribute('list', 'add-word-topics');
  const create = () => {
    if (!en.value.trim()) { en.focus(); return; }
    if (!topic.value.trim()) { topic.focus(); return; }
    add({ en: en.value, ru: ru.value, topic: topic.value });
  };
  screen(
    topicList,
    el('h1', {}, t('add_to_set')),
    search,
    results,
    el('strong', {}, t('create_word')),
    en, ru, topic,
    el('button', { onclick: create }, t('save')),
    status,
  );
  search.focus();
}

// Homework overview for parents: progress, cancel, history

async function showHomework() {
  setBack(showTopics);
  let data;
  try { data = await getJson('/assignments'); } catch (error) { fail(error); return; }
  const cancel = (assignment) => confirmThen(t('cancel_homework_confirm'), async () => {
    await postJson(`/assignments/${assignment.id}/cancel`);
    showHomework();
  });
  const activeCards = data.active.map((assignment) => {
    const parts = assignment.total + assignment.paper_total;
    const percent = parts ? Math.round(((assignment.done + assignment.paper_done) / parts) * 100) : 0;
    const paper = assignment.paper_total ? ` · 📄 ${assignment.paper_done}/${assignment.paper_total}` : '';
    return el('div', { class: 'homework-card' },
      el('div', { class: 'row' },
        el('span', { class: 'title grow' }, assignment.title),
        el('span', { class: 'sub' }, assignment.to)),
      el('div', { class: 'progress' }, el('span', { style: `width:${percent}%` })),
      el('span', { class: 'sub' }, `${t('words_done', { done: assignment.done, total: assignment.total })}${paper} · ${assignment.mode} · ${t('assigned_on', { date: formatDate(assignment.created_at) })}`),
      el('div', { class: 'model-actions' },
        el('button', { class: 'secondary', onclick: () => cancel(assignment) }, t('cancel_homework')),
        assignment.set_id ? el('button', { class: 'secondary', onclick: () => showSet(assignment.set_id, '', showHomework) }, t('open_set')) : null));
  });
  let shown = SETS_PAGE;
  const finishedList = el('div', { class: 'list' });
  const more = el('button', { class: 'secondary' }, t('show_more'));
  const renderFinished = () => {
    finishedList.replaceChildren(...data.finished.slice(0, shown).map((assignment) => el('div', { class: 'item' },
      el('span', { class: 'texts' },
        el('span', { class: 'title' }, assignment.title),
        el('span', { class: 'sub' }, `${assignment.to} · ${t('words_done', { done: assignment.done, total: assignment.total })} · ${formatDate(assignment.finished_at)} · ${statusLabel(assignment.status)}`)))));
    more.hidden = data.finished.length <= shown;
  };
  more.addEventListener('click', () => { shown += SETS_PAGE; renderFinished(); });
  renderFinished();
  screen(
    el('h1', {}, t('homework_list')),
    data.active.length || data.finished.length ? null : el('p', { class: 'muted' }, t('homework_none')),
    data.active.length ? el('strong', {}, t('homework_now')) : null,
    data.active.length ? el('div', { class: 'list' }, ...activeCards) : null,
    data.finished.length ? el('strong', {}, t('homework_finished')) : null,
    data.finished.length ? finishedList : null,
    data.finished.length ? more : null,
  );
}

// Photos of a homework set (draft or saved), loaded with the auth header

const photoCache = new Map();

function photoImg(setId, assetId, className = 'photo', zoom = true) {
  const img = el('img', { class: className, alt: '', loading: 'lazy' });
  const key = `${setId}/${assetId}`;
  if (!photoCache.has(key)) {
    photoCache.set(key, api(`/sets/${setId}/photos/${assetId}`)
      .then((response) => response.blob())
      .then((blob) => URL.createObjectURL(blob))
      .catch(() => { photoCache.delete(key); return null; }));
  }
  photoCache.get(key).then((url) => { if (url) img.src = url; });
  // Tap to see a worksheet at full width.
  if (zoom) img.addEventListener('click', () => img.classList.toggle('zoomed'));
  return img;
}

function kindLabel(kinds, code) {
  return kinds.find((kind) => kind.code === code)?.label || code;
}

function taskHeading(kinds, task) {
  return task.title ? `${kindLabel(kinds, task.kind)} · ${task.title}` : kindLabel(kinds, task.kind);
}

// Add words to a saved set right on its screen: search the dictionary or take a whole topic.
function setWordAdder(setId, topics, backTo) {
  const reload = () => showSet(setId, '', backTo, window.scrollY);
  const results = el('div', { class: 'list' });
  results.hidden = true;
  const search = el('input', { type: 'search', placeholder: `🔍 ${t('search_dictionary')}`, autocapitalize: 'off' });
  let timer = null;
  search.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const query = search.value.trim();
      if (!query) { results.hidden = true; return; }
      try {
        const found = await postJson('/words/search', { q: query });
        results.replaceChildren(...found.words.map((word) => el('button', {
          class: 'item', onclick: () => postJson(`/sets/${setId}/words`, { word_id: word.id }).then(reload).catch(fail),
        },
        el('span', { class: 'texts' },
          el('span', { class: 'title' }, wordTitle(word)),
          el('span', { class: 'sub' }, Object.values(word.translations || {}).find(Boolean) || '')),
        el('span', { class: 'sub' }, '+'))));
        results.hidden = found.words.length === 0;
      } catch (error) { results.hidden = true; }
    }, 250);
  });
  return [
    search,
    results,
    topics.length ? topicPicker(topics, (topicId) => postJson(`/sets/${setId}/topic`, { topic_id: topicId }).then(reload).catch(fail)) : null,
    el('button', { class: 'secondary', onclick: () => showAddWord(setId, topics, backTo) }, t('create_word')),
  ];
}

async function showSet(setId, message = '', backTo = showSets, scrollY = 0) {
  setBack(backTo);
  let data;
  try { data = await getJson(`/sets/${setId}`); } catch (error) { fail(error); return; }
  const status = el('p', { class: 'status' });
  const setStatus = (text, kind = '') => { status.className = `status ${kind}`; status.textContent = text; };
  const heading = el('h1', {}, data.set.archived ? `🗄 ${data.set.title}` : data.set.title);
  const rename = () => askTopicTitle(data.set.title, async (title) => {
    await postJson(`/sets/${setId}`, { title });
    showSet(setId, '', backTo);
  }, t('draft_name'));
  const recipient = choiceGroup(data.members.map((member) => ({ value: String(member.id), label: member.name })));
  const mode = choiceGroup(data.modes.map((option) => ({ value: option.code, label: option.label })));
  applyDefaults(data.defaults, recipient, mode);
  const assignButton = el('button', {}, t('assign'));
  assignButton.addEventListener('click', async () => {
    assignButton.disabled = true;
    try {
      await postJson(`/sets/${setId}/assign`, { assign_to: Number(recipient.value), mode: mode.value });
      showSet(setId, t('assigned_ok'), backTo);
    } catch (error) { setStatus(errorText(error), 'error'); assignButton.disabled = false; }
  });
  const assignments = data.assignments.length
    ? el('div', { class: 'list' }, ...data.assignments.map((assignment) => el('div', { class: 'item' },
      el('span', { class: 'texts' },
        el('span', { class: 'title' }, `${assignment.to} · ${formatDate(assignment.created_at)}`),
        el('span', { class: 'sub' }, `${assignment.mode} · ${statusLabel(assignment.status)}`)))))
    : el('p', { class: 'muted' }, t('never_assigned'));
  const removeWord = (word) => postJson(`/sets/${setId}/words/${word.id}/delete`).then(() => showSet(setId, '', backTo, window.scrollY)).catch(fail);
  const wordList = (words) => el('div', { class: 'list' }, ...words.map((word) => el('div', { class: `item${word.archived ? ' excluded' : ''}` },
    el('span', { class: 'texts' }, el('span', { class: 'title' }, word.text), el('span', { class: 'sub' }, word.ru)),
    el('button', { class: 'icon', title: t('remove_from_set'), 'aria-label': t('remove_from_set'), onclick: () => removeWord(word) }, '✕'))));
  const firstWordsTask = data.tasks.find((task) => task.kind === 'words');
  const taskCards = data.tasks.map((task) => {
    const words = data.words.filter((word) => word.task_id === task.id || (!word.task_id && task === firstWordsTask));
    return el('div', { class: 'task-card' },
      el('strong', {}, DRILL_KINDS.includes(task.kind) ? `${taskHeading(data.task_kinds, task)}: ${words.length}` : taskHeading(data.task_kinds, task)),
      DRILL_KINDS.includes(task.kind) && words.length ? wordList(words) : null,
      ...(task === firstWordsTask ? setWordAdder(setId, data.topics, backTo) : []),
      task.instructions ? el('p', { class: 'instructions' }, task.instructions) : null,
      task.photos.length ? el('div', { class: 'photo-strip' }, ...task.photos.map((id) => photoImg(setId, id))) : null);
  });
  screen(
    heading,
    el('button', { class: 'secondary', onclick: rename }, t('rename')),
    el('strong', {}, t('assign_again')),
    field(t('assign_to'), recipient),
    field(t('mode'), mode),
    assignButton,
    status,
    el('strong', {}, t('set_assignments')),
    assignments,
    el('strong', {}, t('tasks')),
    el('p', { class: 'muted' }, t('set_edit_note')),
    ...taskCards,
    ...(firstWordsTask ? [] : setWordAdder(setId, data.topics, backTo)),
    el('div', { class: 'spacer' }),
    data.set.archived
      ? el('button', { class: 'secondary', onclick: () => postJson(`/sets/${setId}/restore`).then(() => showSet(setId, '', showSets)).catch(fail) }, t('restore_set'))
      : el('button', { class: 'danger', onclick: () => confirmThen(t('archive_set_confirm'), async () => {
        await postJson(`/sets/${setId}/archive`);
        showSets();
      }) }, t('archive_set')),
  );
  if (message) setStatus(message, 'ok');
  if (scrollY) window.scrollTo(0, scrollY);
}

async function createHomework() {
  try { showDraft((await postJson('/imports')).id, showSets); } catch (error) { fail(error); }
}

// Homework draft: an ordered list of tasks (words, paper work, notes), each with its own photos

// Word picture: a thumbnail next to the word; tapping it opens the cut-out editor.

function wordThumb(ctx, state) {
  const button = el('button', { class: 'word-thumb', type: 'button', title: t('word_picture'), 'aria-label': t('word_picture') });
  const render = () => {
    const { id, user } = state.image;
    if (id) button.replaceChildren(photoImg(ctx.setId, id, 'photo', false));
    else if (!user && state.item.current_image && state.item.existing_id) {
      const img = el('img', { class: 'photo', alt: '' });
      fillImage(img, { id: state.item.existing_id, image_id: `word-${state.item.existing_id}` });
      button.replaceChildren(img);
    } else button.replaceChildren(el('span', { class: 'word-thumb-empty' }, '🖼+'));
  };
  button.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    openPictureEditor(ctx, state, render);
  });
  render();
  return button;
}

function openPictureEditor(ctx, state, onChange) {
  const pages = ctx.photos();
  const crop = state.item.crop;
  const overlay = el('div', { class: 'cropper' });
  const status = el('p', { class: 'status' });
  const setStatus = (text, kind = '') => { status.className = `status ${kind}`; status.textContent = text; };
  const stage = el('div', { class: 'crop-stage' });
  const frame = el('div', { class: 'crop-frame' }, ...['nw', 'ne', 'sw', 'se'].map((corner) => el('span', { class: `crop-handle ${corner}` })));
  let source = null;
  let box = null; // [y_min, x_min, y_max, x_max] in 0-1000 of the page
  const close = () => { overlay.remove(); document.body.classList.remove('no-scroll'); };
  const choose = (image) => { state.image = image; onChange(); close(); };
  const place = () => {
    frame.style.top = `${box[0] / 10}%`;
    frame.style.left = `${box[1] / 10}%`;
    frame.style.height = `${(box[2] - box[0]) / 10}%`;
    frame.style.width = `${(box[3] - box[1]) / 10}%`;
  };
  const showPage = (id, initial = null) => {
    source = id;
    box = initial ? [...initial] : [250, 250, 750, 750];
    stage.replaceChildren(photoImg(ctx.setId, id, 'crop-image', false), frame);
    place();
  };
  const clamp = (value, low, high) => Math.min(Math.max(value, low), high);
  frame.addEventListener('pointerdown', (event) => {
    event.preventDefault();
    const corner = [...event.target.classList].find((name) => ['nw', 'ne', 'sw', 'se'].includes(name)) || 'move';
    const rect = stage.getBoundingClientRect();
    const start = [event.clientX, event.clientY];
    const from = [...box];
    frame.setPointerCapture(event.pointerId);
    const move = (moveEvent) => {
      let dy = ((moveEvent.clientY - start[1]) / rect.height) * 1000;
      let dx = ((moveEvent.clientX - start[0]) / rect.width) * 1000;
      let [top, left, bottom, right] = from;
      if (corner === 'move') {
        dy = clamp(dy, -top, 1000 - bottom);
        dx = clamp(dx, -left, 1000 - right);
        top += dy; bottom += dy; left += dx; right += dx;
      } else {
        if (corner.includes('n')) top = clamp(top + dy, 0, bottom - 40);
        if (corner.includes('s')) bottom = clamp(bottom + dy, top + 40, 1000);
        if (corner.includes('w')) left = clamp(left + dx, 0, right - 40);
        if (corner.includes('e')) right = clamp(right + dx, left + 40, 1000);
      }
      box = [top, left, bottom, right];
      place();
    };
    const stop = () => {
      frame.removeEventListener('pointermove', move);
      frame.removeEventListener('pointerup', stop);
      frame.removeEventListener('pointercancel', stop);
    };
    frame.addEventListener('pointermove', move);
    frame.addEventListener('pointerup', stop);
    frame.addEventListener('pointercancel', stop);
  });

  const doneButton = el('button', {}, t('picture_done'));
  doneButton.addEventListener('click', async () => {
    doneButton.disabled = true;
    setStatus(t('uploading'));
    try {
      const result = await postJson(`/imports/${ctx.setId}/crop`, { photo: source, box: box.map(Math.round) });
      state.item.crop = { photo: source, box: box.map(Math.round) };
      choose({ id: result.id, user: true });
    } catch (error) {
      doneButton.disabled = false;
      setStatus(error.message === 'crop_too_small' ? t('picture_too_small') : errorText(error), 'error');
    }
  });
  const fileInput = el('input', { type: 'file', accept: 'image/*', hidden: true });
  fileInput.addEventListener('change', async () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    setStatus(t('uploading'));
    try {
      const blob = await shrinkImage(file);
      const result = await (await api(`/imports/${ctx.setId}/word-picture`, { method: 'POST', body: blob, contentType: blob.type || 'application/octet-stream' })).json();
      choose({ id: result.id, user: true });
    } catch (error) { setStatus(errorText(error), 'error'); }
  });
  const otherPages = pages.length > 1
    ? el('div', { class: 'section' },
      el('span', { class: 'sub' }, t('picture_other_page')),
      el('div', { class: 'photo-strip' }, ...pages.map((id) => el('button', { class: 'photo-pick', onclick: () => showPage(id) }, photoImg(ctx.setId, id, 'photo', false)))))
    : null;

  if (pages.length) showPage(crop && pages.includes(crop.photo) ? crop.photo : pages[0], crop && pages.includes(crop.photo) ? crop.box : null);
  overlay.append(...present(
    el('strong', {}, `${t('word_picture')}: ${state.en.value || state.item.en || ''}`),
    state.item.current_image && !state.image.user ? el('p', { class: 'muted' }, t('picture_kept')) : null,
    pages.length ? el('p', { class: 'muted' }, t('picture_hint')) : el('p', { class: 'muted' }, t('no_photos')),
    pages.length ? stage : null,
    pages.length ? doneButton : null,
    status,
    otherPages,
    fileInput,
    el('button', { class: 'secondary', onclick: () => fileInput.click() }, t('picture_upload')),
    el('div', { class: 'row' },
      el('button', { class: 'secondary grow', onclick: close }, t('cancel')),
      el('button', { class: 'secondary grow', onclick: () => choose({ id: null, user: true }) }, t('picture_remove'))),
  ));
  document.body.classList.add('no-scroll');
  document.body.append(overlay);
}

// "+ Whole topic" opens the family topics as the app's own list (not a native select); a tap hands the id to onPick.
function topicPicker(topics, onPick) {
  const button = el('button', { class: 'secondary', type: 'button' }, t('add_topic'));
  const list = el('div', { class: 'list' });
  const filter = el('input', { type: 'search', placeholder: `🔍 ${t('search')}`, autocapitalize: 'off' });
  const panel = el('div', { class: 'section picker' }, el('span', { class: 'sub' }, t('add_topic_hint')), topics.length > 8 ? filter : null, list);
  panel.hidden = true;
  const render = () => {
    const query = filter.value.trim().toLowerCase();
    list.replaceChildren(...topics.filter((topic) => topic.title.toLowerCase().includes(query)).map((topic) => el('button', {
      class: 'item', type: 'button',
      onclick: async (event) => {
        const item = event.currentTarget;
        item.disabled = true;
        try { await onPick(topic.id); panel.hidden = true; } finally { item.disabled = false; }
      },
    }, el('span', { class: 'texts' }, el('span', { class: 'title' }, topic.title)), el('span', { class: 'sub' }, '+'))));
  };
  filter.addEventListener('input', render);
  button.addEventListener('click', () => {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) { filter.value = ''; render(); }
  });
  return el('div', { class: 'section' }, button, panel);
}

function removeButton(onClick) {
  return el('button', {
    class: 'icon', type: 'button', title: t('remove_word'), 'aria-label': t('remove_word'),
    onclick: (event) => { event.preventDefault(); event.stopPropagation(); onClick(); },
  }, '✕');
}

function wordsEditor(items, defaultTopic, ctx) {
  const rows = el('div', { class: 'list draft-list' });
  const knownRows = el('div', { class: 'list draft-list' });
  const rowState = [];
  // Where new (typed or recognized) words are filed in the dictionary; dictionary words keep their topics.
  const allTopic = el('input', { type: 'text', maxLength: 100, placeholder: t('draft_topic') });
  allTopic.setAttribute('list', 'draft-topics');
  allTopic.value = items.find((item) => item.topic)?.topic || defaultTopic || '';
  const topicField = field(t('new_words_topic'), el('div', { class: 'row' },
    el('span', { class: 'grow' }, allTopic),
    el('button', { class: 'secondary', type: 'button', onclick: () => applyTopic() }, '↓')));
  const syncLists = () => {
    rows.hidden = rows.childElementCount === 0;
    knownRows.hidden = knownRows.childElementCount === 0;
    topicField.hidden = !rowState.some((state) => !state.item.existing_id);
  };
  const addRow = (item) => {
    const known = Boolean(item.existing_id);
    const state = {
      item,
      en: el('input', { type: 'text', value: item.en || '', maxLength: 100, placeholder: 'English', autocapitalize: 'off' }),
      ru: el('input', { type: 'text', value: item.ru || '', maxLength: 200, placeholder: t('translation') }),
      topic: el('input', { type: 'text', value: item.topic || '', maxLength: 100, placeholder: t('draft_topic') }),
      image: { id: item.image_id || null, user: Boolean(item.image_user) },
    };
    state.topic.setAttribute('list', 'draft-topics');
    // Known words are reused as they are, so they get a compact read-only line.
    const fields = known
      ? el('div', { class: 'draft-fields compact' },
        el('span', { class: 'title' }, item.en),
        el('span', { class: 'sub' }, [item.ru, state.topic.value].filter(Boolean).join(' · ')))
      : el('div', { class: 'draft-fields' }, state.en, state.ru, state.topic);
    const card = el('div', { class: 'draft-row' }, wordThumb(ctx, state), fields, removeButton(() => {
      rowState.splice(rowState.indexOf(state), 1);
      card.remove();
      syncLists();
      refreshKnown();
    }));
    state.card = card;
    rowState.push(state);
    // Words the model found already in the dictionary are listed apart; picked ones stay on top.
    (known && !item.manual ? knownRows : rows).append(card);
    syncLists();
    return state;
  };
  // Rows unticked in older drafts were left out of the homework anyway.
  items.filter((item) => item.include !== false).forEach((item) => addRow(item));
  syncLists();

  // Pick an existing word (from any topic) into this homework without duplicating it.
  const dictionarySearch = el('input', { type: 'search', placeholder: `🔍 ${t('search_dictionary')}`, autocapitalize: 'off' });
  const dictionaryResults = el('div', { class: 'list' });
  dictionaryResults.hidden = true;
  // Returns the row of a dictionary word, adding it when the homework does not have it yet.
  const addExisting = (word) => {
    const present = rowState.find((state) => state.item.existing_id === word.id
      || state.en.value.trim().toLowerCase() === word.text.toLowerCase());
    if (present) return present;
    const translation = Object.values(word.translations || {}).find(Boolean) || '';
    return addRow({
      en: word.text, ru: translation, topic: '', existing_id: word.id, manual: true, current_image: Boolean(word.image_id),
    });
  };
  const pickWord = (word) => {
    addExisting(word).card.scrollIntoView({ block: 'center' });
    dictionarySearch.value = '';
    dictionaryResults.hidden = true;
  };
  const addTopic = async (topicId) => {
    const { words } = await getJson(`/topics/${topicId}/words`);
    words.filter((word) => word.type !== 'verb').forEach(addExisting);
    const verbs = words.filter((word) => word.type === 'verb');
    if (verbs.length && ctx.addVerbs) ctx.addVerbs(verbs);
  };
  let searchTimer = null;
  dictionarySearch.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(async () => {
      const query = dictionarySearch.value.trim();
      if (!query) { dictionaryResults.hidden = true; return; }
      try {
        const found = await postJson('/words/search', { q: query, type: 'word' });
        dictionaryResults.replaceChildren(...found.words.map((word) => el('button', { class: 'item', onclick: () => pickWord(word) },
          el('span', { class: 'texts' },
            el('span', { class: 'title' }, word.text),
            el('span', { class: 'sub' }, Object.values(word.translations || {}).find(Boolean) || '')),
          el('span', { class: 'sub' }, '+'))));
        dictionaryResults.hidden = found.words.length === 0;
      } catch (error) { dictionaryResults.hidden = true; }
    }, 250);
  });

  const applyTopic = () => rowState.forEach((state) => {
    if (state.item.manual) return; // picked from another topic: it only joins the homework
    state.topic.value = allTopic.value;
    const sub = state.item.existing_id && state.card.querySelector('.sub');
    if (sub) sub.textContent = [state.item.ru, allTopic.value].filter(Boolean).join(' · ');
  });
  const knownCount = () => rowState.filter((state) => state.item.existing_id && !state.item.manual).length;
  const knownHeading = el('span', { class: 'sub' });
  const refreshKnown = () => { knownHeading.textContent = knownCount() ? `${t('already_known')}: ${knownCount()}` : ''; };
  refreshKnown();

  const node = el('div', { class: 'section' },
    rows,
    dictionarySearch,
    dictionaryResults,
    ctx.topics?.length ? topicPicker(ctx.topics, addTopic) : null,
    el('button', { class: 'secondary', onclick: () => { const state = addRow({ en: '', ru: '', topic: allTopic.value }); state.en.focus(); } }, t('create_word')),
    topicField,
    knownHeading,
    knownRows);
  return {
    node,
    collect: () => rowState.map((state) => ({
      en: state.en.value, ru: state.ru.value, topic: state.topic.value,
      existing_id: state.item.existing_id || null, manual: Boolean(state.item.manual),
      current_image: Boolean(state.item.current_image), crop: state.item.crop || null,
      image_id: state.image.id, image_user: state.image.user,
    })),
    // The first new word without a topic, so saving can point at it.
    missingTopic: () => rowState.find((state) => state.en.value.trim() && !state.item.existing_id && !state.topic.value.trim()),
  };
}

const DRILL_KINDS = ['words', 'verbs'];
const VERB_FORM = /^[a-z][a-z']*(\/[a-z][a-z']*)*$/;

function wordTitle(word) {
  return word.type === 'verb' && word.forms ? [word.text, word.forms.past, word.forms.participle].join(' – ') : word.text;
}

// Irregular verbs of a draft. Verbs come from the bot's list and are shown as they are; a verb missing
// from the list (e.g. read from a tutor's message) keeps editable forms and joins the list on save.
function verbsEditor(items, list = []) {
  const listed = new Map(list.map((verb) => [verb.base, verb]));
  const rows = el('div', { class: 'list draft-list' });
  const rowState = [];
  const clean = (value) => String(value || '').trim().toLowerCase().replace(/\s*\/\s*/g, '/');
  const addRow = (item, { top = false } = {}) => {
    const verb = listed.get(clean(item.base));
    const field = (value, placeholder) => el('input', { type: 'text', value: value || '', maxLength: 40, placeholder, autocapitalize: 'off' });
    const state = verb
      ? { item, verb }
      : {
        item,
        base: field(item.base, 'V1'),
        past: field(item.past, 'V2'),
        participle: field(item.participle, 'V3'),
        ru: el('input', { type: 'text', value: item.ru || '', maxLength: 200, placeholder: t('translation') }),
      };
    const fields = verb
      ? el('div', { class: 'draft-fields compact' },
        el('span', { class: 'title' }, [verb.base, verb.past, verb.participle].join(' – ')),
        el('span', { class: 'sub' }, [verb.ru, item.existing_id ? t('already_known') : ''].filter(Boolean).join(' · ')))
      : el('div', { class: 'draft-fields' },
        el('div', { class: 'row verb-forms' }, state.base, state.past, state.participle), state.ru,
        el('span', { class: 'sub' }, t('verb_new')));
    const card = el('div', { class: 'draft-row' }, fields, removeButton(() => {
      rowState.splice(rowState.indexOf(state), 1);
      card.remove();
    }));
    rowState.push(state);
    if (top) rows.prepend(card); else rows.append(card);
    return state;
  };
  const baseOf = (state) => (state.verb ? state.verb.base : clean(state.base.value));
  const has = (base) => rowState.some((state) => baseOf(state) === base);
  items.filter((item) => item.include !== false).forEach((item) => addRow(item));

  const options = el('datalist', { id: 'irregular-verbs' }, ...list.map((verb) => el('option', { value: verb.base }, `${verb.past} ${verb.participle} · ${verb.ru}`)));
  const pick = el('input', { type: 'text', maxLength: 40, placeholder: t('verb_pick'), autocapitalize: 'off' });
  pick.setAttribute('list', 'irregular-verbs');
  const add = () => {
    const base = clean(pick.value);
    if (!base) { pick.focus(); return; }
    pick.value = '';
    if (has(base)) return;
    const state = addRow({ base, past: '', participle: '', ru: '' }, { top: true });
    if (!state.verb) state.past.focus();
  };
  pick.addEventListener('keydown', (event) => { if (event.key === 'Enter') add(); });
  pick.addEventListener('change', () => { if (listed.has(clean(pick.value))) add(); });
  const node = el('div', { class: 'section' },
    el('span', { class: 'sub' }, t('verb_hint')),
    el('div', { class: 'row' }, pick, el('button', { class: 'secondary', onclick: add }, t('create_verb'))),
    options,
    rows);
  return {
    node,
    collect: () => rowState.map((state) => (state.verb
      ? { base: state.verb.base, past: state.verb.past, participle: state.verb.participle, ru: state.verb.ru, existing_id: state.item.existing_id || null }
      : { base: state.base.value, past: state.past.value, participle: state.participle.value, ru: state.ru.value, existing_id: null })),
    // Dictionary verbs (from a whole topic) join once, matched by base form.
    addExisting: (verbs) => verbs.forEach((verb) => {
      if (has(clean(verb.text))) return;
      addRow({ base: verb.text, past: verb.forms?.past || '', participle: verb.forms?.participle || '', existing_id: verb.id });
    }),
    // The first verb missing from the list with a missing or malformed form, so saving can point at it.
    invalid: () => {
      for (const state of rowState) {
        if (state.verb || !state.base.value.trim()) continue;
        const bad = [state.base, state.past, state.participle].find((input) => !VERB_FORM.test(clean(input.value)));
        if (bad) return bad;
      }
      return null;
    },
  };
}

async function showDraft(setId, backTo = null) {
  setBack(backTo);
  let data;
  try { data = await getJson(`/imports/${setId}`); } catch (error) {
    try { labels = (await getJson('/topics')).labels || labels; } catch { /* keep keys */ }
    const text = error.message === 'draft_not_available' ? t('draft_unavailable') : errorText(error);
    app.replaceChildren(el('p', { class: 'status error' }, text), el('button', { onclick: showTopics }, t('topics')));
    return;
  }
  labels = data.labels || labels;
  document.title = t('draft_title');
  const photos = [...data.photos];
  const views = [];
  const tasksBox = el('div', { class: 'section' });
  const gallery = el('div', { class: 'photo-grid' });
  const status = el('p', { class: 'status' });
  const setStatus = (text, kind = '') => { status.className = `status ${kind}`; status.textContent = text; };

  const refreshPhotos = () => {
    views.forEach((view) => view.renderPhotos());
    gallery.replaceChildren(...photos.map((id) => {
      const owners = views.filter((view) => view.task.photos.includes(id)).map((view) => view.label());
      return el('div', { class: 'photo-tile' },
        photoImg(setId, id),
        el('span', { class: owners.length ? 'sub' : 'sub warn' }, owners.length ? t('photo_in_task', { tasks: owners.join(', ') }) : t('photo_unused')));
    }));
    if (!photos.length) gallery.replaceChildren(el('p', { class: 'muted' }, t('no_photos')));
  };
  const reorder = () => tasksBox.replaceChildren(...views.map((view) => view.node));
  const move = (view, delta) => {
    const index = views.indexOf(view);
    const target = index + delta;
    if (target < 0 || target >= views.length) return;
    views.splice(index, 1);
    views.splice(target, 0, view);
    reorder();
  };

  const upload = async (file) => {
    const blob = await shrinkImage(file);
    const result = await (await api(`/imports/${setId}/photos`, { method: 'POST', body: blob, contentType: blob.type || 'application/octet-stream' })).json();
    photos.push(result.id);
    return result.id;
  };

  const buildTaskView = (task) => {
    task.photos = [...(task.photos || [])];
    const view = { task };
    const enabled = el('input', { type: 'checkbox', checked: task.enabled !== false });
    const title = el('input', { type: 'text', value: task.title || '', maxLength: 200, placeholder: t('task_title') });
    const instructions = el('textarea', { value: task.instructions || '', maxLength: 4000, rows: 4, placeholder: t('task_instructions') });
    const words = task.kind === 'words' ? wordsEditor(task.items || [], '', { setId, photos: () => photos, topics: data.topics, addVerbs })
      : task.kind === 'verbs' ? verbsEditor(task.items || [], data.verbs || []) : null;
    view.addVerbs = words?.addExisting;
    view.label = () => title.value.trim() || kindLabel(data.task_kinds, task.kind);
    title.addEventListener('input', refreshPhotos);

    const strip = el('div', { class: 'photo-strip' });
    const picker = el('div', { class: 'section picker' });
    picker.hidden = true;
    const fileInput = el('input', { type: 'file', accept: 'image/*', multiple: true, hidden: true });
    fileInput.addEventListener('change', async () => {
      setStatus(t('uploading'));
      try {
        for (const file of fileInput.files || []) task.photos.push(await upload(file));
        setStatus('');
      } catch (error) { setStatus(errorText(error), 'error'); }
      fileInput.value = '';
      picker.hidden = true;
      refreshPhotos();
    });
    const renderPicker = () => picker.replaceChildren(
      el('span', { class: 'sub' }, photos.length ? t('gallery_hint') : t('no_photos')),
      el('div', { class: 'photo-grid' }, ...photos.filter((id) => !task.photos.includes(id)).map((id) => el('button', {
        class: 'photo-pick', onclick: () => { task.photos.push(id); picker.hidden = true; refreshPhotos(); },
      }, photoImg(setId, id, 'photo')))),
      fileInput,
      el('button', { class: 'secondary', onclick: () => fileInput.click() }, t('upload_photo')));
    view.renderPhotos = () => strip.replaceChildren(...task.photos.map((id) => el('div', { class: 'photo-tile' },
      photoImg(setId, id),
      el('button', { class: 'link', onclick: () => { task.photos = task.photos.filter((other) => other !== id); refreshPhotos(); } }, t('detach_photo')))));

    const card = el('div', { class: 'task-card' });
    const syncEnabled = () => card.classList.toggle('excluded', !enabled.checked);
    enabled.addEventListener('change', syncEnabled);
    const instructionsBlock = DRILL_KINDS.includes(task.kind)
      ? el('details', { open: Boolean(task.instructions) }, el('summary', {}, t('task_instructions')), instructions)
      : el('label', {}, t('task_instructions'), instructions);
    card.append(
      el('div', { class: 'row' },
        el('strong', { class: 'grow' }, kindLabel(data.task_kinds, task.kind)),
        el('button', { class: 'icon', title: t('move_up'), 'aria-label': t('move_up'), onclick: () => move(view, -1) }, '↑'),
        el('button', { class: 'icon', title: t('move_down'), 'aria-label': t('move_down'), onclick: () => move(view, 1) }, '↓'),
        el('button', { class: 'icon', title: t('delete_task'), 'aria-label': t('delete_task'), onclick: () => confirmThen(t('delete_task'), async () => {
          views.splice(views.indexOf(view), 1);
          reorder();
          refreshPhotos();
        }) }, '✕')),
      el('label', { class: 'inline-check' }, enabled, t('task_enabled')),
      title,
      ...(words ? [words.node] : []),
      instructionsBlock,
      strip,
      el('button', { class: 'secondary', onclick: () => { renderPicker(); picker.hidden = !picker.hidden; } }, t('attach_photo')),
      picker);
    syncEnabled();
    view.node = card;
    view.collect = () => ({
      kind: task.kind, title: title.value, instructions: instructions.value, enabled: enabled.checked,
      items: words ? words.collect() : [], photos: task.photos,
    });
    view.missingTopic = () => (enabled.checked && words?.missingTopic ? words.missingTopic() : null);
    view.invalidVerb = () => (enabled.checked && words?.invalid ? words.invalid() : null);
    return view;
  };

  // Verbs of a whole topic go to the first verbs task, made when the draft has none.
  function addVerbs(verbs) {
    let view = views.find((other) => other.task.kind === 'verbs');
    if (!view) {
      view = buildTaskView({ kind: 'verbs', title: '', instructions: '', enabled: true, items: [], photos: [] });
      views.push(view);
      reorder();
    }
    view.addVerbs(verbs);
  }

  data.tasks.forEach((task) => views.push(buildTaskView(task)));
  reorder();
  refreshPhotos();

  // One button per task kind adds that task at once.
  const addTask = (kind) => {
    const view = buildTaskView({ kind, title: '', instructions: '', enabled: true, items: [], photos: [] });
    views.push(view);
    reorder();
    refreshPhotos();
    view.node.scrollIntoView({ block: 'start' });
  };

  const titleInput = el('input', { type: 'text', value: data.set.title, maxLength: 200 });
  const recipient = choiceGroup([
    ...data.members.map((member) => ({ value: String(member.id), label: member.name })),
    { value: '', label: t('dont_assign') },
  ]);
  const mode = choiceGroup(data.modes.map((option) => ({ value: option.code, label: option.label })));
  applyDefaults(data.defaults, recipient, mode);
  const saveButton = el('button', {}, t('save_draft'));

  // Unsaved work is stored a moment after every change, so closing the page loses nothing.
  const autosaveNote = el('span', { class: 'sub' });
  let autosaveTimer = null;
  let closed = false;
  const autosave = async () => {
    clearTimeout(autosaveTimer);
    autosaveTimer = null;
    if (closed) return;
    try {
      await postJson(`/imports/${setId}`, { title: titleInput.value, tasks: views.map((view) => view.collect()) });
      autosaveNote.textContent = t('draft_autosaved');
    } catch (error) {
      if (error.message === 'draft_not_available') closed = true;
    }
  };
  const scheduleAutosave = () => {
    if (closed) return;
    autosaveNote.textContent = '';
    clearTimeout(autosaveTimer);
    autosaveTimer = setTimeout(autosave, 1200);
  };
  [tasksBox, titleInput].forEach((node) => {
    node.addEventListener('input', scheduleAutosave);
    node.addEventListener('change', scheduleAutosave);
  });
  new MutationObserver(scheduleAutosave).observe(tasksBox, { childList: true, subtree: true });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden' && autosaveTimer) autosave();
  });

  saveButton.addEventListener('click', async () => {
    const missing = views.map((view) => view.missingTopic()).find(Boolean);
    if (missing) { missing.topic.focus(); return; }
    const badVerb = views.map((view) => view.invalidVerb()).find(Boolean);
    if (badVerb) { setStatus(t('verb_forms_invalid'), 'error'); badVerb.focus(); return; }
    saveButton.disabled = true;
    setStatus(t('uploading'));
    clearTimeout(autosaveTimer);
    autosaveTimer = null;
    closed = true;
    try {
      const result = await postJson(`/imports/${setId}/save`, {
        title: titleInput.value, tasks: views.map((view) => view.collect()), mode: mode.value,
        assign_to: recipient.value ? Number(recipient.value) : null,
      });
      const message = result.assignment_id ? t('draft_saved_assigned') : t('draft_saved');
      screen(
        el('h1', {}, result.title),
        el('p', { class: 'status ok' }, message.replace('{count}', result.word_count)),
        el('button', { onclick: () => (webApp?.close ? webApp.close() : showTopics()) }, t('back')),
        el('button', { class: 'secondary', onclick: () => showSet(setId) }, t('open_set')),
      );
    } catch (error) {
      saveButton.disabled = false;
      closed = error.message === 'draft_not_available';
      const known = { draft_not_available: t('draft_unavailable'), draft_empty: t('draft_empty'), invalid_verb_forms: t('verb_forms_invalid') };
      setStatus(known[error.message] || errorText(error), 'error');
    }
  });

  screen(
    el('datalist', { id: 'draft-topics' }, ...data.topics.map((topic) => el('option', { value: topic.title }))),
    el('h1', {}, t('draft_title')),
    el('label', {}, t('draft_name'), titleInput),
    el('strong', {}, t('tasks')),
    tasksBox,
    field(t('add_task'), el('div', { class: 'choices' }, ...data.task_kinds.map((kind) => el('button', {
      class: 'choice', type: 'button', onclick: () => addTask(kind.code),
    }, kind.label)))),
    el('strong', {}, t('gallery')),
    gallery,
    field(t('assign_to'), recipient),
    field(t('mode'), mode),
    saveButton,
    status,
    autosaveNote,
    el('div', { class: 'spacer' }),
    el('button', { class: 'danger', onclick: () => confirmThen(t('delete_draft_confirm'), async () => {
      closed = true;
      clearTimeout(autosaveTimer);
      await postJson(`/imports/${setId}/cancel`);
      showSets();
    }) }, t('delete_draft')),
  );
}

const importId = Number(new URLSearchParams(location.search).get('import'));
const startScreen = new URLSearchParams(location.search).get('pictures') ? showPictures : showTopics;
if (importId) showDraft(importId); else startScreen();
