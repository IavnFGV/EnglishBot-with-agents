const app = document.getElementById('app');
const webApp = window.Telegram?.WebApp;
const session = Number(new URLSearchParams(location.search).get('session'));
const initData = webApp?.initData || '';
let state = null;
let busy = false;
let mediumSelected = [];
let mediumMask = '';
let mediumDirty = false;
let mediumSave = null;
let mediumTimer = null;
let mediumChecking = false;
const imageCache = new Map();
let labels = {};
const offlineLabels = { connection: 'Connection lost. Your progress is saved.', retry: 'Try again', expired: 'Please reopen the game from Telegram.' };

function t(key, values = {}) {
  let value = labels[key] || offlineLabels[key] || key;
  for (const [name, content] of Object.entries(values)) value = value.replace(`{${name}}`, content);
  return value;
}

function syncTheme() {
  if (webApp?.colorScheme) document.documentElement.dataset.theme = webApp.colorScheme;
}

webApp?.ready();
webApp?.expand();
syncTheme();
webApp?.onEvent?.('themeChanged', syncTheme);

function haptic(kind) {
  try { webApp?.HapticFeedback?.notificationOccurred(kind); } catch (_) { /* optional */ }
}

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
  app.append(el('div', 'error-text', error.message === 'expired_init_data' ? t('expired') : t('connection')));
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
    if (state.feedback === 'correct') haptic('success');
    else if (state.feedback === 'incorrect') haptic('error');
    render();
  } catch (error) {
    if (['stale_question', 'session_completed', 'invalid_answer'].includes(error.message)) await refresh();
    else showError(error);
  } finally { busy = false; }
}

function showFallback(frame) {
  const image = el('img', 'picture picture-placeholder');
  image.src = '/mini-app/no-image.png';
  image.alt = '';
  frame.replaceChildren(image);
}

async function loadImage(assetId, frame) {
  if (!assetId) { showFallback(frame); return; }
  const spinnerTimer = setTimeout(() => {
    if (frame.isConnected) {
      const spinner = el('div', 'picture-spinner');
      spinner.setAttribute('role', 'status');
      spinner.setAttribute('aria-label', t('loading'));
      frame.replaceChildren(spinner);
    }
  }, 150);
  let url = imageCache.get(assetId);
  try {
    if (!url) {
      const blob = await (await api(`/media/${assetId}`)).blob();
      url = URL.createObjectURL(blob);
    }
    const image = el('img', 'picture');
    image.src = url;
    await image.decode();
    imageCache.set(assetId, url);
    if (frame.isConnected) frame.replaceChildren(image);
  } catch (_) {
    if (url) {
      imageCache.delete(assetId);
      URL.revokeObjectURL(url);
    }
    if (frame.isConnected) showFallback(frame);
  } finally { clearTimeout(spinnerTimer); }
}

let voices = null;
let voiceIndex = null;
let audio = null;
let audioLoading = false;

async function play(path) {
  if (audioLoading) return;
  audioLoading = true;
  try {
    const blob = await (await api(path)).blob();
    const url = URL.createObjectURL(blob);
    if (audio) audio.pause();
    audio = new Audio(url);
    audio.onended = () => URL.revokeObjectURL(url);
    await audio.play();
  } catch (_) {
    const feedback = app.querySelector('.feedback');
    if (feedback) feedback.replaceChildren(el('span', 'pill neutral', t('audio_unavailable')));
  } finally { audioLoading = false; }
}

function listen() {
  if (busy) return;
  play(voiceIndex === null ? '/tts' : `/tts/${voiceIndex}`);
}

function showVoiceName() {
  const caption = app.querySelector('.voice-name');
  if (caption && voices && voiceIndex !== null) caption.textContent = t('voice_name', { voice: voices[voiceIndex] });
}

async function switchVoice() {
  if (busy || audioLoading) return;
  try {
    if (!voices) {
      const data = await (await api('/voices')).json();
      voices = data.voices;
      if (voiceIndex === null) voiceIndex = data.current;
    }
  } catch (_) {
    const feedback = app.querySelector('.feedback');
    if (feedback) feedback.replaceChildren(el('span', 'pill neutral', t('audio_unavailable')));
    return;
  }
  if (!voices.length) return;
  voiceIndex = (voiceIndex + 1) % voices.length;
  showVoiceName();
  await play(`/tts/${voiceIndex}`);
}

function button(text, action, value, className = '') {
  const node = el('button', className, text);
  node.onclick = () => act(action, value);
  return node;
}

function drawMediumSelection() {
  const answer = app.querySelector('.answer');
  const letters = [...state.question.letters];
  const chosen = mediumSelected.map(index => letters[index]);
  let position = 0;
  answer.replaceChildren(...mediumMask.split(' ').map(slot => {
    if (!slot) return el('span', 'slot-gap');
    const letter = chosen[position++];
    return el('span', letter ? 'slot filled' : 'slot', letter || '');
  }));
  app.querySelectorAll('.letters button').forEach((choice, index) => {
    const selected = mediumSelected.includes(index);
    choice.textContent = letters[index];
    choice.classList.toggle('used', selected);
    choice.disabled = selected || letters[index] === ' ';
  });
}

async function flushMedium() {
  if (mediumSave) {
    await mediumSave;
    return flushMedium();
  }
  if (!mediumDirty) return;
  const selected = [...mediumSelected];
  mediumDirty = false;
  mediumSave = (async () => {
    state = await (await api('/answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: state.question.token, action: 'set_medium', value: selected })
    })).json();
  })();
  try { await mediumSave; }
  finally { mediumSave = null; }
  if (mediumDirty) return flushMedium();
  render();
}

function editMedium(action, index) {
  if (busy || mediumChecking) return;
  if (action === 'add') {
    if (mediumSelected.includes(index) || mediumSelected.length >= mediumMask.split(' ').filter(Boolean).length) return;
    mediumSelected.push(index);
  } else if (mediumSelected.length) mediumSelected.pop();
  else return;
  drawMediumSelection();
  mediumDirty = true;
  clearTimeout(mediumTimer);
  mediumTimer = setTimeout(() => flushMedium().catch(showError), 200);
}

async function checkMedium() {
  if (busy || mediumChecking) return;
  mediumChecking = true;
  clearTimeout(mediumTimer);
  app.querySelectorAll('button').forEach(choice => choice.disabled = true);
  try {
    await flushMedium();
    mediumChecking = false;
    await act('check');
  } catch (error) {
    mediumChecking = false;
    showError(error);
  }
}

function renderHomeworkProgress(progress, big = false) {
  const panel = el('div', big ? 'homework-progress big' : 'homework-progress');
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 200 200');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', t('homework_progress', { completed: progress.completed, total: progress.total }));
  const addSvg = (tag, attributes, content) => {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [name, value] of Object.entries(attributes)) {
      if (name === 'fill' || name === 'stroke') node.style[name] = String(value);
      else node.setAttribute(name, String(value));
    }
    if (content !== undefined) node.textContent = content;
    svg.append(node);
  };
  const segments = progress.segments;
  const sweep = 360 / Math.max(1, segments.length);
  const gap = Math.min(4, sweep * .12);
  const wedge = (radius, start, end) => {
    const point = angle => {
      const radians = angle * Math.PI / 180;
      return [100 + radius * Math.cos(radians), 100 + radius * Math.sin(radians)];
    };
    const first = point(start);
    const last = point(end);
    return `M 100 100 L ${first[0]} ${first[1]} A ${radius} ${radius} 0 ${end - start > 180 ? 1 : 0} 1 ${last[0]} ${last[1]} Z`;
  };
  segments.forEach((segment, index) => {
    const start = -90 + index * sweep + gap / 2;
    const end = -90 + (index + 1) * sweep - gap / 2;
    const value = Math.max(0, Math.min(1, segment.value));
    const color = segment.hard_clear ? 'var(--accent)' : value >= 1 ? 'var(--good)' : value > 0 ? 'var(--sun)' : 'var(--line)';
    addSvg('path', { d: wedge(82, start, end), fill: 'var(--line)' });
    if (value > 0) addSvg('path', { d: wedge(24 + 58 * value, start, end), fill: color });
  });
  addSvg('circle', { cx: 100, cy: 100, r: big ? 30 : 36, fill: 'var(--surface)' });
  addSvg('text', { x: 100, y: big ? 108 : 112, 'text-anchor': 'middle', fill: 'var(--ink)', 'font-size': big ? 24 : 34, 'font-weight': 900 }, `${progress.completed}/${progress.total}`);
  panel.append(svg);
  return panel;
}

function confetti() {
  const layer = el('div', 'confetti');
  layer.setAttribute('aria-hidden', 'true');
  const colors = ['var(--sun)', 'var(--accent)', 'var(--good)', 'var(--bad)'];
  for (let index = 0; index < 36; index += 1) {
    const piece = el('i');
    piece.style.left = `${Math.random() * 100}%`;
    piece.style.background = colors[index % colors.length];
    piece.style.animationDelay = `${Math.random() * .6}s`;
    piece.style.animationDuration = `${1.4 + Math.random() * 1.2}s`;
    layer.append(piece);
  }
  setTimeout(() => layer.remove(), 3500);
  return layer;
}

function render() {
  app.replaceChildren();
  if (state?.status === 'completed') {
    const card = el('div', 'card finish');
    card.append(el('div', 'medal', '🏆'));
    card.append(el('div', 'prompt', t('great')));
    if (state.homework_progress) card.append(renderHomeworkProgress(state.homework_progress, true));
    card.append(el('div', 'hint', t('outcome', state.summary)));
    if (state.paper_left) card.append(el('div', 'paper', t('paper_left', { count: state.paper_left })));
    const close = el('button', '', t('back'));
    close.onclick = () => webApp?.close();
    card.append(close);
    app.append(card, confetti());
    return;
  }
  const q = state.question;
  const top = el('header', 'top');
  const topText = el('div', 'top-text');
  topText.append(el('span', 'top-word', `${t('word')} ${q.number}/${q.total}`), el('span', 'top-done', `${q.completed}/${q.total} ${t('done')}`));
  top.append(topText);
  if (state.homework_progress) top.append(renderHomeworkProgress(state.homework_progress));
  app.append(top);
  if (!state.homework_progress) {
    const bar = el('div', 'bar');
    const fill = el('span');
    fill.style.width = `${100 * q.completed / Math.max(q.total, 1)}%`;
    bar.append(fill); app.append(bar);
  }
  const card = el('div', 'card');
  const pictureFrame = el('div', 'picture-frame');
  card.append(pictureFrame);
  loadImage(q.image_asset_id, pictureFrame);
  card.append(el('div', 'prompt', q.prompt));
  if (q.task) card.append(el('div', 'hint task', q.task));
  if (q.hint && q.hint !== q.prompt) card.append(el('div', 'hint', q.hint));
  if (q.type === 'typed_answer' && q.first_letter) card.append(el('div', 'hint', t('starts', { letter: q.first_letter })));
  app.append(card);
  if (q.type === 'multiple_choice') {
    const choices = el('div', 'choices');
    q.options.forEach((option, index) => choices.append(button(option, 'easy', index)));
    app.append(choices);
  } else if (q.type === 'jumbled_letters') {
    mediumSelected = [...q.selected];
    mediumMask = q.answer_mask.split(' ').map(slot => slot ? '_' : '').join(' ');
    app.append(el('div', 'answer'));
    const letters = el('div', 'letters');
    [...q.letters].forEach((letter, index) => {
      const choice = el('button', '', letter);
      choice.onclick = () => editMedium('add', index);
      letters.append(choice);
    });
    app.append(letters);
    drawMediumSelection();
    const actions = el('div', 'actions');
    const backspace = el('button', 'secondary backspace', '⌫');
    backspace.setAttribute('aria-label', 'Backspace');
    backspace.onclick = () => editMedium('backspace');
    const check = el('button', '', t('check'));
    check.onclick = checkMedium;
    actions.append(backspace, check);
    app.append(actions);
  } else {
    const input = el('input', 'answer');
    input.autocomplete = 'off'; input.autocapitalize = 'off'; input.spellcheck = false;
    input.placeholder = t('type');
    input.maxLength = 200;
    const submitTyped = () => { if (input.value.trim()) act('hard', input.value); else input.focus(); };
    input.addEventListener('keydown', event => { if (event.key === 'Enter') submitTyped(); });
    app.append(input);
    const actions = el('div', 'actions');
    const check = el('button', '', t('check'));
    check.onclick = submitTyped;
    actions.append(check);
    if (q.can_skip_hard) actions.append(button(t('skip'), 'skip', null, 'secondary'));
    app.append(actions);
  }
  const feedback = el('div', 'feedback');
  const pill = {
    correct: ['correct', `✓ ${t('feedback_correct')}`],
    incorrect: ['error', `✗ ${t('feedback_incorrect', { answer: state.correct_answer || '' })}`],
    skipped: ['neutral', t('feedback_skipped')],
  }[state.feedback];
  if (pill) feedback.append(el('span', `pill ${pill[0]}`, pill[1]));
  app.append(feedback);
  if (q.tts_available) {
    const sound = el('div', 'sound');
    const listenButton = el('button', 'secondary listen', t('listen'));
    listenButton.onclick = listen;
    const voiceButton = el('button', 'secondary listen', t('other_voice'));
    voiceButton.onclick = switchVoice;
    sound.append(listenButton, voiceButton);
    app.append(sound, el('div', 'voice-name'));
    showVoiceName();
  }
  if (q.type === 'typed_answer') app.querySelector('input.answer')?.focus();
}

if (!session || !initData) showError(new Error('unauthorized'));
else refresh();
