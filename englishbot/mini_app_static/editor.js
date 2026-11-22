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
    data.topics.length ? list : el('p', { class: 'muted' }, t('no_topics')),
  );
}

function askTopicTitle(initial, onSubmit) {
  const previousBack = backHandler;
  const input = el('input', { type: 'text', value: initial, maxLength: 200, placeholder: t('topic_title') });
  const status = el('p', { class: 'status' });
  const submit = async () => {
    if (!input.value.trim()) { input.focus(); return; }
    try { await onSubmit(input.value.trim()); } catch (error) { status.className = 'status error'; status.textContent = errorText(error); }
  };
  input.addEventListener('keydown', (event) => { if (event.key === 'Enter') submit(); });
  setBack(previousBack || showTopics);
  screen(
    el('label', {}, t('topic_title'), input),
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

showTopics();
