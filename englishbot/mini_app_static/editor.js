'use strict';

const app = document.getElementById('app');
const webApp = window.Telegram?.WebApp;
const initData = webApp?.initData || '';
const MAX_UPLOAD_SIDE = 1600;
const MAX_UPLOAD_BYTES = 900 * 1024;

let labels = {};
let languages = [];
let backHandler = null;
const imageCache = new Map();

webApp?.ready();
webApp?.expand();
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
          el('span', { class: 'title' }, word.text),
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

  const save = async () => {
    if (!textInput.value.trim()) { textInput.focus(); return; }
    const payload = { text: textInput.value, translations: Object.fromEntries(Object.entries(translationInputs).map(([code, input]) => [code, input.value])) };
    saveButton.disabled = true;
    try {
      const saved = word
        ? await postJson(`/words/${word.id}`, payload)
        : await postJson(`/topics/${topic.id}/words`, payload);
      const isNew = !word;
      word = saved;
      if (isNew) { showWord(topic, saved, true); return; }
      setStatus(t('saved'), 'ok');
    } catch (error) { setStatus(errorText(error), 'error'); } finally { saveButton.disabled = false; }
  };
  const saveButton = el('button', { onclick: save }, t('save'));
  [textInput, ...Object.values(translationInputs)].forEach((input) => input.addEventListener('keydown', (event) => { if (event.key === 'Enter') save(); }));

  screen(
    el('label', {}, t('word'), textInput),
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
    section.replaceChildren(
      el('strong', {}, t('photo')),
      preview,
      fileInput,
      el('button', { class: 'secondary', onclick: () => fileInput.click() }, t('choose_photo')),
      urlInput,
      el('button', { class: 'secondary', onclick: useUrl }, t('use_url')),
      word.image_id ? el('button', { class: 'link', onclick: () => update(() => postJson(`/words/${word.id}/image/delete`)) }, t('remove_photo')) : null,
    );
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

function applyDefaults(defaults, recipient, mode) {
  if (defaults?.recipient && [...recipient.options].some((option) => option.value === String(defaults.recipient))) recipient.value = String(defaults.recipient);
  if (defaults?.mode) mode.value = defaults.mode;
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
    const percent = assignment.total ? Math.round((assignment.done / assignment.total) * 100) : 0;
    return el('div', { class: 'homework-card' },
      el('div', { class: 'row' },
        el('span', { class: 'title grow' }, assignment.title),
        el('span', { class: 'sub' }, assignment.to)),
      el('div', { class: 'progress' }, el('span', { style: `width:${percent}%` })),
      el('span', { class: 'sub' }, `${t('words_done', { done: assignment.done, total: assignment.total })} · ${assignment.mode} · ${t('assigned_on', { date: formatDate(assignment.created_at) })}`),
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

async function showSet(setId, message = '', backTo = showSets) {
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
  const recipient = el('select', {}, ...data.members.map((member) => el('option', { value: String(member.id) }, member.name)));
  const mode = el('select', {}, ...data.modes.map((option) => el('option', { value: option.code }, option.label)));
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
  const removeWord = (word) => postJson(`/sets/${setId}/words/${word.id}/delete`).then(() => showSet(setId, '', backTo)).catch(fail);
  const words = el('div', { class: 'list' }, ...data.words.map((word) => el('div', { class: `item${word.archived ? ' excluded' : ''}` },
    el('span', { class: 'texts' }, el('span', { class: 'title' }, word.text), el('span', { class: 'sub' }, word.ru)),
    el('button', { class: 'icon', title: t('remove_from_set'), 'aria-label': t('remove_from_set'), onclick: () => removeWord(word) }, '✕'))));
  screen(
    heading,
    el('button', { class: 'secondary', onclick: rename }, t('rename')),
    el('strong', {}, t('assign_again')),
    el('label', {}, t('assign_to'), recipient),
    el('label', {}, t('mode'), mode),
    assignButton,
    status,
    el('strong', {}, t('set_assignments')),
    assignments,
    el('strong', {}, `${t('set_words')}: ${data.words.length}`),
    el('p', { class: 'muted' }, t('set_edit_note')),
    data.words.length ? words : null,
    el('button', { class: 'secondary', onclick: () => showAddWord(setId, data.topics, backTo) }, t('add_to_set')),
    el('div', { class: 'spacer' }),
    data.set.archived
      ? el('button', { class: 'secondary', onclick: () => postJson(`/sets/${setId}/restore`).then(() => showSet(setId, '', showSets)).catch(fail) }, t('restore_set'))
      : el('button', { class: 'danger', onclick: () => confirmThen(t('archive_set_confirm'), async () => {
        await postJson(`/sets/${setId}/archive`);
        showSets();
      }) }, t('archive_set')),
  );
  if (message) setStatus(message, 'ok');
}

// Homework draft produced from forwarded tutor messages

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
  const topicList = el('datalist', { id: 'draft-topics' }, ...data.topics.map((topic) => el('option', { value: topic.title })));
  const titleInput = el('input', { type: 'text', value: data.set.title, maxLength: 200 });
  const rows = el('div', { class: 'list draft-list' });
  const rowState = [];

  const knownRows = el('div', { class: 'list draft-list' });
  const addRow = (item) => {
    const known = Boolean(item.existing_id);
    const state = {
      item,
      include: el('input', { type: 'checkbox', checked: item.include !== false }),
      en: el('input', { type: 'text', value: item.en || '', maxLength: 100, placeholder: 'English', autocapitalize: 'off' }),
      ru: el('input', { type: 'text', value: item.ru || '', maxLength: 200, placeholder: t('translation') }),
      topic: el('input', { type: 'text', value: item.topic || '', maxLength: 100, placeholder: t('draft_topic') }),
    };
    state.topic.setAttribute('list', 'draft-topics');
    // Known words are reused as they are, so they get a compact read-only line.
    const fields = known
      ? el('div', { class: 'draft-fields compact' },
        el('span', { class: 'title' }, item.en),
        el('span', { class: 'sub' }, [item.ru, state.topic.value].filter(Boolean).join(' · ')))
      : el('div', { class: 'draft-fields' }, state.en, state.ru, state.topic);
    const card = el('label', { class: 'draft-row' }, el('span', { class: 'draft-check' }, state.include), fields);
    state.include.addEventListener('change', () => card.classList.toggle('excluded', !state.include.checked));
    rowState.push(state);
    (known ? knownRows : rows).append(card);
    return state;
  };
  data.items.forEach(addRow);
  const knownCount = data.items.filter((item) => item.existing_id).length;

  const allTopic = el('input', { type: 'text', maxLength: 100, placeholder: t('draft_topic') });
  allTopic.setAttribute('list', 'draft-topics');
  const firstTopic = data.items.find((item) => item.topic)?.topic || '';
  allTopic.value = firstTopic;
  const applyTopic = () => rowState.forEach((state) => {
    state.topic.value = allTopic.value;
    const sub = state.item.existing_id && state.include.closest('.draft-row')?.querySelector('.sub');
    if (sub) sub.textContent = [state.item.ru, allTopic.value].filter(Boolean).join(' · ');
  });

  const recipient = el('select', {},
    ...data.members.map((member) => el('option', { value: String(member.id) }, member.name)),
    el('option', { value: '' }, t('dont_assign')));
  const mode = el('select', {}, ...data.modes.map((option) => el('option', { value: option.code }, option.label)));
  applyDefaults(data.defaults, recipient, mode);
  const status = el('p', { class: 'status' });
  const saveButton = el('button', {}, t('save_draft'));

  saveButton.addEventListener('click', async () => {
    const items = rowState.map((state) => ({
      en: state.en.value, ru: state.ru.value, topic: state.topic.value,
      include: state.include.checked, existing_id: state.item.existing_id || null,
    }));
    const chosen = items.filter((item) => item.include && item.en.trim());
    if (!chosen.length) { status.className = 'status error'; status.textContent = t('draft_empty'); return; }
    const missingTopic = rowState.find((state) => state.include.checked && state.en.value.trim() && !state.item.existing_id && !state.topic.value.trim());
    if (missingTopic) { missingTopic.topic.focus(); return; }
    saveButton.disabled = true;
    status.className = 'status'; status.textContent = t('uploading');
    try {
      const result = await postJson(`/imports/${setId}/save`, {
        title: titleInput.value, items, mode: mode.value,
        assign_to: recipient.value ? Number(recipient.value) : null,
      });
      const message = result.assignment_id ? t('draft_saved_assigned') : t('draft_saved');
      screen(
        el('h1', {}, result.title),
        el('p', { class: 'status ok' }, message.replace('{count}', result.word_count)),
        el('button', { onclick: () => (webApp?.close ? webApp.close() : showTopics()) }, t('back')),
        el('button', { class: 'secondary', onclick: showTopics }, t('topics')),
      );
    } catch (error) {
      saveButton.disabled = false;
      status.className = 'status error';
      status.textContent = error.message === 'draft_not_available' ? t('draft_unavailable') : errorText(error);
    }
  });

  screen(
    topicList,
    el('h1', {}, t('draft_title')),
    el('label', {}, t('draft_name'), titleInput),
    el('label', {}, t('draft_topic'), el('div', { class: 'row' }, el('span', { class: 'grow' }, allTopic), el('button', { class: 'secondary', onclick: applyTopic }, '↓'))),
    el('strong', {}, `${t('draft_words')}: ${data.items.length - knownCount}`),
    rows.childElementCount ? rows : null,
    el('button', { class: 'secondary', onclick: () => { const state = addRow({ en: '', ru: '', topic: allTopic.value }); state.en.focus(); } }, t('add_item')),
    knownCount ? el('strong', {}, `${t('already_known')}: ${knownCount}`) : null,
    knownCount ? knownRows : null,
    el('label', {}, t('assign_to'), recipient),
    el('label', {}, t('mode'), mode),
    saveButton,
    status,
    el('div', { class: 'spacer' }),
    el('button', { class: 'danger', onclick: () => confirmThen(t('delete_draft_confirm'), async () => {
      await postJson(`/imports/${setId}/cancel`);
      showSets();
    }) }, t('delete_draft')),
  );
}

const importId = Number(new URLSearchParams(location.search).get('import'));
if (importId) showDraft(importId); else showTopics();
