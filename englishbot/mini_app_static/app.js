const app = document.getElementById('app');
const webApp = window.Telegram?.WebApp;
const session = Number(new URLSearchParams(location.search).get('session'));
const initData = webApp?.initData || '';
let state = null;
let busy = false;
const imageCache = new Map();
let labels = {};
const offlineLabels = { connection: 'Connection lost. Your progress is saved.', retry: 'Try again', expired: 'Please reopen the game from Telegram.' };

function t(key, values = {}) {
  let value = labels[key] || offlineLabels[key] || key;
  for (const [name, content] of Object.entries(values)) value = value.replace(`{${name}}`, content);
  return value;
}

webApp?.ready();
webApp?.expand();

function el(tag, className, text) {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(`/mini-app/api/sessions/${session}${path}`, {
    ...options,
    headers: { 'X-Telegram-Init-Data': initData, ...(options.headers || {}) },
    cache: 'no-store'
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || 'network_error');
  }
  return response;
}

async function refresh() {
  try {
    state = await (await api('')).json();
    labels = state.labels || labels;
    render();
  } catch (error) { showError(error); }
}

function showError(error) {
  app.replaceChildren();
  app.append(el('div', 'feedback error', error.message === 'expired_init_data' ? t('expired') : t('connection')));
  const retry = el('button', '', t('retry'));
  retry.onclick = refresh;
  app.append(retry);
}

async function act(action, value) {
  if (busy || !state?.question) return;
  busy = true;
  const token = state.question.token;
  app.querySelectorAll('button').forEach(button => button.disabled = true);
  try {
    state = await (await api('/answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, action, value })
    })).json();
    render();
  } catch (error) {
    if (error.message === 'stale_question' || error.message === 'session_completed') await refresh();
    else showError(error);
  } finally { busy = false; }
}

async function loadImage(assetId, node) {
  if (imageCache.has(assetId)) { node.src = imageCache.get(assetId); return; }
  try {
    const blob = await (await api(`/media/${assetId}`)).blob();
    const url = URL.createObjectURL(blob);
    imageCache.set(assetId, url);
    if (node.isConnected) node.src = url;
  } catch (_) { node.remove(); }
}

async function listen() {
  if (busy) return;
  try {
    const blob = await (await api('/tts')).blob();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.onended = () => URL.revokeObjectURL(url);
    await audio.play();
  } catch (_) { app.querySelector('.feedback').textContent = t('audio_unavailable'); }
}

function button(text, action, value, className = '') {
  const node = el('button', className, text);
  node.onclick = () => act(action, value);
  return node;
}

function render() {
  app.replaceChildren();
  if (state?.status === 'completed') {
    const card = el('div', 'card');
    card.append(el('div', 'prompt', t('great')));
    card.append(el('div', 'hint', t('correct_answers', { count: state.summary.correct })));
    const close = el('button', '', t('back'));
    close.onclick = () => webApp?.close();
    card.append(close);
    app.append(card);
    return;
  }
  const q = state.question;
  const top = el('div', 'top');
  top.append(el('span', '', `${t('word')} ${q.number}/${q.total}`), el('span', '', `${q.completed}/${q.total} ${t('done')}`));
  app.append(top);
  const bar = el('div', 'bar');
  const fill = el('span');
  fill.style.width = `${100 * q.completed / Math.max(q.total, 1)}%`;
  bar.append(fill); app.append(bar);
  const card = el('div', 'card');
  if (q.image_asset_id) {
    const img = el('img', 'picture');
    img.alt = '';
    card.append(img);
    loadImage(q.image_asset_id, img);
  }
  card.append(el('div', 'prompt', q.prompt));
  if (q.hint) card.append(el('div', 'hint', q.hint));
  if (q.type === 'typed_answer' && q.first_letter) card.append(el('div', 'hint', t('starts', { letter: q.first_letter })));
  app.append(card);
  if (q.type === 'multiple_choice') {
    const choices = el('div', 'choices');
    q.options.forEach((option, index) => choices.append(button(option, 'easy', index)));
    app.append(choices);
  } else if (q.type === 'jumbled_letters') {
    app.append(el('div', 'answer', q.answer_mask));
    const letters = el('div', 'letters');
    [...q.letters].forEach((letter, index) => {
      const choice = button(letter, 'add', index);
      choice.disabled = q.selected.includes(index) || letter === ' ';
      letters.append(choice);
    });
    app.append(letters);
    const actions = el('div', 'actions');
    actions.append(button('⌫', 'backspace', null, 'secondary'), button(t('check'), 'check'));
    app.append(actions);
  } else {
    const input = el('input', 'answer');
    input.autocomplete = 'off'; input.autocapitalize = 'off'; input.spellcheck = false;
    input.placeholder = t('type');
    input.maxLength = 200;
    input.addEventListener('keydown', event => { if (event.key === 'Enter') act('hard', input.value); });
    app.append(input);
    const actions = el('div', 'actions');
    const check = el('button', '', t('check'));
    check.onclick = () => act('hard', input.value);
    actions.append(check);
    if (q.can_skip_hard) actions.append(button(t('skip'), 'skip', null, 'secondary'));
    app.append(actions);
  }
  const feedback = el('div', `feedback ${state.feedback === 'correct' ? 'correct' : state.feedback === 'incorrect' ? 'error' : ''}`, state.feedback === 'correct' ? t('feedback_correct') : state.feedback === 'incorrect' ? t('feedback_incorrect') : state.feedback === 'skipped' ? t('feedback_skipped') : '');
  app.append(feedback);
  if (q.tts_available) {
    const listenButton = el('button', 'secondary', t('listen'));
    listenButton.onclick = listen;
    app.append(listenButton);
  }
}

if (!session || !initData) showError(new Error('unauthorized'));
else refresh();
