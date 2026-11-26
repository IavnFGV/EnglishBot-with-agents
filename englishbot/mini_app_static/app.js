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
    if (gameMode) loadSprites();
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

async function act(action, value, beforeRender) {
  if (busy || !state?.question) return;
  busy = true;
  const token = state.question.token;
  const previous = state.question;
  app.querySelectorAll('button').forEach(button => button.disabled = true);
  try {
    const next = await (await api('/answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, action, value })
    })).json();
    if (next.feedback === 'correct') haptic('success');
    else if (next.feedback === 'incorrect') haptic('error');
    if (beforeRender) await beforeRender(next, previous).catch(() => {});
    state = next;
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

// Ball game: a skin over multiple-choice questions. The server still checks every answer.
const GAME_KEY = 'englishbot.gameMode';
const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
let gameMode = true;
let streak = 0;
try { gameMode = localStorage.getItem(GAME_KEY) !== 'off'; } catch (_) { /* storage is optional */ }

function setGameMode(on) {
  gameMode = on;
  try { localStorage.setItem(GAME_KEY, on ? 'on' : 'off'); } catch (_) { /* storage is optional */ }
  render();
}

const wait = ms => new Promise(resolve => setTimeout(resolve, reducedMotion ? Math.min(ms, 300) : ms));

const HEROINE_SVG = `
<svg viewBox="0 0 120 160" aria-hidden="true">
  <ellipse class="h-shadow" cx="60" cy="154" rx="30" ry="5"/>
  <g class="h-body">
    <rect x="47" y="124" width="10" height="24" rx="4" fill="#ffd9b8"/>
    <rect x="63" y="124" width="10" height="24" rx="4" fill="#ffd9b8"/>
    <ellipse cx="51" cy="149" rx="9" ry="5" fill="#e0573f"/>
    <ellipse cx="69" cy="149" rx="9" ry="5" fill="#e0573f"/>
    <path d="M40 92 Q60 84 80 92 L84 128 Q60 134 36 128 Z" fill="#ffd04d"/>
    <path d="M44 104 L76 104 L80 128 Q60 133 40 128 Z" fill="#3b63f3"/>
    <rect x="46" y="88" width="5" height="18" rx="2" fill="#3b63f3"/>
    <rect x="69" y="88" width="5" height="18" rx="2" fill="#3b63f3"/>
    <path d="M43 94 L30 116" stroke="#ffd9b8" stroke-width="8" stroke-linecap="round"/>
    <g class="h-arm"><path d="M77 94 L90 116" stroke="#ffd9b8" stroke-width="8" stroke-linecap="round"/><circle cx="90" cy="116" r="5.5" fill="#ffd9b8"/></g>
    <g class="h-head">
      <g fill="#7a4a24">
        <circle cx="34" cy="48" r="12"/><circle cx="86" cy="48" r="12"/><circle cx="38" cy="30" r="13"/>
        <circle cx="82" cy="30" r="13"/><circle cx="60" cy="22" r="16"/><circle cx="31" cy="66" r="10"/><circle cx="89" cy="66" r="10"/>
        <circle cx="36" cy="80" r="8"/><circle cx="84" cy="80" r="8"/>
      </g>
      <circle cx="60" cy="56" r="25" fill="#ffd9b8"/>
      <g fill="#8d5a2e"><circle cx="45" cy="34" r="9"/><circle cx="60" cy="30" r="10"/><circle cx="75" cy="34" r="9"/></g>
      <circle cx="44" cy="64" r="5" fill="#ffaaa0" opacity=".7"/><circle cx="76" cy="64" r="5" fill="#ffaaa0" opacity=".7"/>
      <g class="h-eyes" fill="#1d2a44"><circle cx="51" cy="56" r="3.4"/><circle cx="69" cy="56" r="3.4"/></g>
      <path class="h-smile" d="M51 66 Q60 75 69 66" stroke="#1d2a44" stroke-width="3" fill="none" stroke-linecap="round"/>
      <ellipse class="h-oops" cx="60" cy="69" rx="3.5" ry="4.5" fill="#1d2a44"/>
    </g>
  </g>
</svg>`;

function balloonSpots(count) {
  const rows = Math.ceil(count / 2);
  return Array.from({ length: count }, (_, index) => {
    const row = Math.floor(index / 2);
    const lonely = index === count - 1 && count % 2 === 1;
    const left = lonely ? 50 : index % 2 ? 74 : 26;
    const top = 3 + row * (50 / Math.max(rows, 1)) + (index % 2 && !lonely ? 9 : 0);
    return [left, top];
  });
}

function centerIn(field, node, fx = .5, fy = .5) {
  const box = field.getBoundingClientRect();
  const rect = node.getBoundingClientRect();
  return [rect.left - box.left + rect.width * fx, rect.top - box.top + rect.height * fy];
}

// Drawn heroine poses live on the server; without them the SVG heroine stays.
const POSES = ['idle', 'windup', 'throw', 'happy', 'oops'];
let sprites = null;
let spritesLoading = null;

function loadSprites() {
  if (!spritesLoading) {
    spritesLoading = Promise.all(POSES.map(async pose => {
      const url = URL.createObjectURL(await (await api(`/heroine/${pose}`)).blob());
      const image = new Image();
      image.src = url;
      await image.decode();
      return [pose, url];
    })).then(entries => { sprites = Object.fromEntries(entries); }, () => { sprites = null; });
  }
  return spritesLoading;
}

function dressHeroine(heroine) {
  if (sprites) {
    // All poses stay in the DOM so switching is instant and never flickers.
    heroine.replaceChildren(...POSES.map(pose => {
      const image = el('img', `sprite pose-${pose}`);
      image.alt = '';
      image.src = sprites[pose];
      return image;
    }));
    heroine.classList.add('drawn');
  } else heroine.innerHTML = HEROINE_SVG;
}

function setPose(heroine, pose) {
  heroine.classList.remove('idle', 'windup', 'throw', 'happy', 'oops');
  void heroine.offsetWidth; // restart CSS animations of the new pose
  heroine.classList.add(pose);
}

function throwBall(field, heroine, balloon, facingRight) {
  const ball = el('div', 'ball');
  field.append(ball);
  const drawn = heroine.classList.contains('drawn');
  const handX = drawn ? (facingRight ? .84 : .16) : .78;
  const [x0, y0] = centerIn(field, heroine, handX, drawn ? .14 : .22);
  const [x1, y1] = centerIn(field, balloon);
  const peak = Math.min(y0, y1) - 80;
  const point = k => [x0 + (x1 - x0) * k, (1 - k) * (1 - k) * y0 + 2 * (1 - k) * k * peak + k * k * y1];
  const frames = Array.from({ length: 17 }, (_, step) => {
    const k = step / 16;
    const [x, y] = point(k);
    const squash = k > .94 ? 'scale(1.25, .8)' : 'scale(1)';
    return { transform: `translate(${x - 13}px, ${y - 13}px) rotate(${k * 720}deg) ${squash}` };
  });
  const duration = reducedMotion ? 1 : 560;
  if (!reducedMotion) {
    for (let index = 1; index <= 6; index += 1) {
      const dot = el('i', 'trail');
      field.append(dot);
      setTimeout(() => {
        const [x, y] = point(index / 7);
        dot.style.transform = `translate(${x - 5}px, ${y - 5}px)`;
        dot.classList.add('on');
        setTimeout(() => dot.remove(), 420);
      }, duration * index / 7);
    }
  }
  const flight = ball.animate(frames, { duration, easing: 'cubic-bezier(.3, .1, .6, 1)', fill: 'forwards' });
  return flight.finished.then(() => ball.remove(), () => ball.remove());
}

function burst(field, balloon, good) {
  const [x, y] = centerIn(field, balloon);
  const colors = good ? ['var(--sun)', 'var(--good)', 'var(--accent)', '#ff7ab6'] : ['var(--line)', 'var(--muted)'];
  const count = good ? 18 : 6;
  for (let index = 0; index < count; index += 1) {
    const bit = el('i', good && index % 3 === 0 ? 'spark star' : 'spark');
    if (bit.classList.contains('star')) bit.textContent = '★';
    const angle = (index / count) * Math.PI * 2;
    const distance = good ? 60 + Math.random() * 40 : 30;
    bit.style.left = `${x}px`; bit.style.top = `${y}px`;
    bit.style.color = colors[index % colors.length];
    if (!bit.textContent) bit.style.background = colors[index % colors.length];
    bit.style.setProperty('--dx', `${Math.cos(angle) * distance}px`);
    bit.style.setProperty('--dy', `${Math.sin(angle) * distance}px`);
    field.append(bit);
    setTimeout(() => bit.remove(), 1000);
  }
  if (good) {
    const plus = el('div', 'plus-one', '+1');
    plus.style.left = `${x}px`; plus.style.top = `${y}px`;
    field.append(plus);
    setTimeout(() => plus.remove(), 1100);
  }
}

function renderBallGame(q) {
  const field = el('div', 'playfield');
  const heroine = el('div', 'heroine idle');
  dressHeroine(heroine);
  if (!sprites) loadSprites().then(() => { if (sprites && heroine.isConnected) dressHeroine(heroine); });
  const balloons = q.options.map(() => null);
  balloonSpots(q.options.length).forEach(([left, top], index) => {
    const balloon = el('button', `balloon tone-${index % 4}`);
    balloon.append(el('span', 'balloon-text', q.options[index]));
    balloon.style.left = `${left}%`;
    balloon.style.top = `${top}%`;
    balloon.style.animationDelay = `${index * .18}s, ${.9 + index * .18}s`;
    balloon.onclick = () => {
      if (busy) return;
      balloon.classList.add('target');
      const facingRight = left > 50 || (left === 50 && Math.random() < .5);
      heroine.classList.toggle('face-right', facingRight);
      setPose(heroine, 'windup');
      const flight = wait(240).then(() => {
        setPose(heroine, 'throw');
        return throwBall(field, heroine, balloon, facingRight);
      });
      act('easy', index, async (next, previous) => {
        await flight;
        if (next.feedback === 'correct') {
          streak += 1;
          balloon.classList.add('popped');
          burst(field, balloon, true);
          setPose(heroine, 'happy');
          if (streak >= 2) field.append(el('div', 'streak', `🔥 ${streak}`));
          await wait(1100);
        } else {
          streak = 0;
          balloon.classList.add('wrong');
          burst(field, balloon, false);
          setPose(heroine, 'oops');
          const right = previous.options.indexOf(next.correct_answer);
          if (right >= 0 && balloons[right]) balloons[right].classList.add('reveal');
          await wait(1800);
        }
      });
    };
    balloons[index] = balloon;
    field.append(balloon);
  });
  field.append(heroine);
  if (streak >= 2) field.append(el('div', 'streak calm', `🔥 ${streak}`));
  return field;
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
  const playing = gameMode && q.type === 'multiple_choice';
  if (q.type === 'multiple_choice') {
    const toggle = el('button', 'secondary mode-toggle', gameMode ? t('quiz_mode') : t('game_mode'));
    toggle.onclick = () => { if (!busy) setGameMode(!gameMode); };
    top.append(toggle);
  }
  if (state.homework_progress) top.append(renderHomeworkProgress(state.homework_progress));
  app.append(top);
  if (!state.homework_progress) {
    const bar = el('div', 'bar');
    const fill = el('span');
    fill.style.width = `${100 * q.completed / Math.max(q.total, 1)}%`;
    bar.append(fill); app.append(bar);
  }
  const card = el('div', playing ? 'card compact' : 'card');
  const pictureFrame = el('div', 'picture-frame');
  card.append(pictureFrame);
  loadImage(q.image_asset_id, pictureFrame);
  card.append(el('div', 'prompt', q.prompt));
  if (q.task) card.append(el('div', 'hint task', q.task));
  if (q.hint && q.hint !== q.prompt) card.append(el('div', 'hint', q.hint));
  if (q.type === 'typed_answer' && q.first_letter) card.append(el('div', 'hint', t('starts', { letter: q.first_letter })));
  app.append(card);
  if (playing) app.append(renderBallGame(q));
  else if (q.type === 'multiple_choice') {
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
