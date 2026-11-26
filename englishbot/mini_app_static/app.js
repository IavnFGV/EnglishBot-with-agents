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
    prefetchQuestion(state.question);
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
    prefetchQuestion(next.question);
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

function imageUrl(assetId) {
  if (!imageCache.has(assetId)) {
    const pending = (async () => {
      const url = URL.createObjectURL(await (await api(`/media/${assetId}`)).blob());
      const image = new Image();
      image.src = url;
      await image.decode().catch(() => {});
      return url;
    })();
    pending.catch(() => imageCache.delete(assetId));
    imageCache.set(assetId, pending);
  }
  return imageCache.get(assetId);
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
  try {
    const image = el('img', 'picture');
    image.src = await imageUrl(assetId);
    await image.decode();
    if (frame.isConnected) frame.replaceChildren(image);
  } catch (_) {
    if (frame.isConnected) showFallback(frame);
  } finally { clearTimeout(spinnerTimer); }
}

let voices = null;
let voiceIndex = null;
let audio = null;
let audioLoading = false;

const audioCache = new Map();

function voicePath() {
  return voiceIndex === null ? '/tts' : `/tts/${voiceIndex}`;
}

function audioUrl(token, path) {
  const key = `${token}|${path}`;
  if (!audioCache.has(key)) {
    const pending = (async () => URL.createObjectURL(await (await api(path)).blob()))();
    pending.catch(() => audioCache.delete(key));
    audioCache.set(key, pending);
    // Keep only a few recent clips in memory.
    while (audioCache.size > 8) {
      const [oldKey, oldUrl] = audioCache.entries().next().value;
      audioCache.delete(oldKey);
      oldUrl.then(url => URL.revokeObjectURL(url), () => {});
    }
  }
  return audioCache.get(key);
}

// Fetch the picture and the sound of a question before anyone asks for them.
async function prefetchQuestion(question) {
  if (!question) return;
  if (question.image_asset_id) imageUrl(question.image_asset_id).catch(() => {});
  if (question.tts_available) {
    await ensureVoices();
    audioUrl(question.token, voicePath()).catch(() => {});
  }
}

async function play(path) {
  if (audioLoading || !state?.question) return;
  audioLoading = true;
  try {
    const url = await audioUrl(state.question.token, path);
    if (audio) audio.pause();
    audio = new Audio(url);
    await audio.play();
  } catch (_) {
    const feedback = app.querySelector('.feedback');
    if (feedback) feedback.replaceChildren(el('span', 'pill neutral', t('audio_unavailable')));
  } finally { audioLoading = false; }
}

let voicesLoading = null;

function ensureVoices() {
  if (voices) return Promise.resolve(true);
  if (!voicesLoading) {
    voicesLoading = api('/voices').then(response => response.json()).then(data => {
      voices = data.voices;
      if (voiceIndex === null) voiceIndex = data.current;
      return true;
    }).catch(() => { voicesLoading = null; return false; });
  }
  return voicesLoading;
}

async function listen() {
  if (busy) return;
  // Name the voice on every listen, not only after switching.
  if (await ensureVoices()) showVoiceName();
  play(voicePath());
}

function showVoiceName() {
  const caption = app.querySelector('.voice-name');
  if (caption && voices && voiceIndex !== null) caption.textContent = t('voice_name', { voice: voices[voiceIndex] });
}

// "Other voice" opens the list of voices; a tap on one plays the word in it and closes the list.
async function toggleVoicePicker() {
  const picker = app.querySelector('.voice-picker');
  if (!picker || busy) return;
  if (!picker.hidden) { picker.hidden = true; return; }
  if (!(await ensureVoices())) {
    const feedback = app.querySelector('.feedback');
    if (feedback) feedback.replaceChildren(el('span', 'pill neutral', t('audio_unavailable')));
    return;
  }
  if (!voices.length) return;
  picker.replaceChildren(...voices.map((name, index) => {
    const option = el('button', `secondary voice-option${index === voiceIndex ? ' selected' : ''}`, name);
    option.onclick = () => pickVoice(index);
    return option;
  }));
  picker.hidden = false;
}

async function pickVoice(index) {
  if (busy || audioLoading) return;
  const picker = app.querySelector('.voice-picker');
  if (picker) picker.hidden = true;
  voiceIndex = index;
  showVoiceName();
  await play(`/tts/${voiceIndex}`);
}

function button(text, action, value, className = '') {
  const node = el('button', className, text);
  node.onclick = () => act(action, value);
  return node;
}

function drawMediumSelection(fresh = false) {
  const answer = app.querySelector('.answer');
  const letters = [...state.question.letters];
  const chosen = mediumSelected.map(index => letters[index]);
  let position = 0;
  answer.replaceChildren(...mediumMask.split(' ').map(slot => {
    if (!slot) return el('span', 'slot-gap');
    const letter = chosen[position++];
    const added = fresh && position === chosen.length;
    return el('span', letter ? (added ? 'slot filled fresh' : 'slot filled') : 'slot', letter || '');
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
  drawMediumSelection(action === 'add');
  mediumDirty = true;
  clearTimeout(mediumTimer);
  mediumTimer = setTimeout(() => flushMedium().catch(showError), 200);
}

async function checkMedium(beforeRender) {
  if (busy || mediumChecking) return;
  mediumChecking = true;
  clearTimeout(mediumTimer);
  app.querySelectorAll('button').forEach(choice => choice.disabled = true);
  try {
    await flushMedium();
    mediumChecking = false;
    await act('check', undefined, typeof beforeRender === 'function' ? beforeRender : undefined);
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
const BALL_POSES = ['idle', 'windup', 'throw', 'happy', 'oops'];
const BRIDGE_POSES = ['bridge-stand', 'bridge-carry', 'bridge-walk', 'bridge-leap', 'bridge-fall', 'bridge-wet'];
const SPELL_POSES = ['spell-ready', 'spell-cast', 'spell-success', 'spell-sooty', 'spell-sneeze'];
const spriteUrls = {};
const spriteLoads = {};

function loadPose(pose) {
  if (!spriteLoads[pose]) {
    spriteLoads[pose] = (async () => {
      const url = URL.createObjectURL(await (await api(`/heroine/${pose}`)).blob());
      const image = new Image();
      image.src = url;
      // Decoding only warms the cache; never let it hold the game back.
      await Promise.race([image.decode().catch(() => {}), new Promise(resolve => setTimeout(resolve, 1200))]);
      spriteUrls[pose] = url;
    })();
    spriteLoads[pose].catch(() => { delete spriteLoads[pose]; });
  }
  return spriteLoads[pose];
}

function loadSprites(poses = [...BALL_POSES, ...BRIDGE_POSES, ...SPELL_POSES]) {
  return Promise.all(poses.map(loadPose)).then(() => true, () => false);
}

function makeHeroine(poses, pose, className = '') {
  const heroine = el('div', `heroine ${className}`.trim());
  heroine.dataset.poses = poses.join(' ');
  setPose(heroine, pose);
  const dress = () => {
    // All poses stay in the DOM so switching is instant and never flickers.
    heroine.replaceChildren(...poses.map(name => {
      const image = el('img', 'sprite');
      image.alt = '';
      image.dataset.pose = name;
      image.src = spriteUrls[name];
      return image;
    }));
    heroine.classList.add('drawn');
    setPose(heroine, heroine.dataset.pose);
  };
  if (poses.every(name => spriteUrls[name])) dress();
  else {
    heroine.innerHTML = HEROINE_SVG;
    loadSprites(poses).then(ok => { if (ok && heroine.isConnected) dress(); });
  }
  return heroine;
}

function setPose(heroine, pose) {
  if (heroine.dataset.pose) heroine.classList.remove(heroine.dataset.pose);
  void heroine.offsetWidth; // restart CSS animations of the new pose
  heroine.dataset.pose = pose;
  heroine.classList.add(pose);
  heroine.querySelectorAll('.sprite').forEach(image => image.classList.toggle('on', image.dataset.pose === pose));
}

// Little sound effects synthesized on the fly, so no audio files are needed.
let soundContext = null;

function noiseSource(context, seconds) {
  const buffer = context.createBuffer(1, Math.ceil(context.sampleRate * seconds), context.sampleRate);
  const data = buffer.getChannelData(0);
  for (let index = 0; index < data.length; index += 1) data[index] = Math.random() * 2 - 1;
  const source = context.createBufferSource();
  source.buffer = buffer;
  return source;
}

function envelope(context, start, peak, attack, release) {
  const gain = context.createGain();
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.exponentialRampToValueAtTime(peak, start + attack);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + attack + release);
  gain.connect(context.destination);
  return gain;
}

function tone(context, type, from, to, start, length, peak = .2) {
  const osc = context.createOscillator();
  osc.type = type;
  osc.frequency.setValueAtTime(from, start);
  osc.frequency.exponentialRampToValueAtTime(to, start + length);
  osc.connect(envelope(context, start, peak, .01, length));
  osc.start(start); osc.stop(start + length + .05);
}

const SOUNDS = {
  unlock() {},
  pop(context, now) {
    const noise = noiseSource(context, .12);
    const filter = context.createBiquadFilter();
    filter.type = 'highpass'; filter.frequency.value = 1200;
    noise.connect(filter); filter.connect(envelope(context, now, .5, .003, .09));
    noise.start(now);
  },
  plank(context, now) {
    tone(context, 'triangle', 520, 260, now, .07, .3);
    tone(context, 'square', 180, 120, now, .05, .05);
  },
  chime(context, now) {
    [1047, 1319, 1568, 2093, 2637].forEach((freq, index) => tone(context, 'sine', freq, freq * 1.01, now + index * .07, .5, .12));
  },
  boing(context, now) { tone(context, 'sine', 180, 900, now, .32, .25); },
  splash(context, now) {
    const noise = noiseSource(context, .8);
    const filter = context.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.setValueAtTime(4000, now);
    filter.frequency.exponentialRampToValueAtTime(250, now + .7);
    noise.connect(filter); filter.connect(envelope(context, now, .6, .01, .7));
    noise.start(now);
  },
  whoosh(context, now) {
    const noise = noiseSource(context, .5);
    const filter = context.createBiquadFilter();
    filter.type = 'bandpass'; filter.Q.value = 3;
    filter.frequency.setValueAtTime(400, now);
    filter.frequency.exponentialRampToValueAtTime(3000, now + .4);
    noise.connect(filter); filter.connect(envelope(context, now, .35, .1, .35));
    noise.start(now);
  },
  fart(context, now) {
    const osc = context.createOscillator();
    osc.type = 'sawtooth';
    osc.frequency.setValueAtTime(115, now);
    osc.frequency.exponentialRampToValueAtTime(55, now + .75);
    const wobble = context.createOscillator();
    const depth = context.createGain();
    wobble.frequency.value = 23; depth.gain.value = 35;
    wobble.connect(depth); depth.connect(osc.frequency);
    const filter = context.createBiquadFilter();
    filter.type = 'lowpass'; filter.frequency.value = 520; filter.Q.value = 6;
    osc.connect(filter); filter.connect(envelope(context, now, .5, .03, .75));
    osc.start(now); wobble.start(now); osc.stop(now + .85); wobble.stop(now + .85);
  },
  sneeze(context, now) {
    // "ah... ah..." rising, then a noisy "CHOO".
    tone(context, 'triangle', 330, 470, now, .28, .12);
    tone(context, 'triangle', 380, 620, now + .38, .3, .14);
    const noise = noiseSource(context, .45);
    const filter = context.createBiquadFilter();
    filter.type = 'bandpass'; filter.Q.value = 1.2;
    filter.frequency.setValueAtTime(3200, now + .78);
    filter.frequency.exponentialRampToValueAtTime(900, now + 1.15);
    noise.connect(filter); filter.connect(envelope(context, now + .78, .7, .015, .38));
    noise.start(now + .78);
  },
};

function sfx(kind) {
  try {
    soundContext = soundContext || new (window.AudioContext || window.webkitAudioContext)();
    if (soundContext.state === 'suspended') soundContext.resume();
    SOUNDS[kind](soundContext, soundContext.currentTime + .01);
  } catch (_) { /* sound is optional */ }
}

// Say a question's word aloud (the clip was prefetched when the question appeared).
async function speak(question) {
  if (!question?.tts_available) return;
  try {
    const url = await audioUrl(question.token, voicePath());
    if (soundContext) {
      try {
        const data = await (await fetch(url)).arrayBuffer();
        const buffer = await soundContext.decodeAudioData(data);
        const source = soundContext.createBufferSource();
        source.buffer = buffer;
        source.connect(soundContext.destination);
        source.start();
        return;
      } catch (_) { /* fall back to an audio element */ }
    }
    await new Audio(url).play();
  } catch (_) { /* sound is optional */ }
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
  ball.animate(frames, { duration, easing: 'cubic-bezier(.3, .1, .6, 1)', fill: 'forwards' });
  return wait(duration).then(() => ball.remove());
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
  const heroine = makeHeroine(BALL_POSES, 'idle');
  const balloons = q.options.map(() => null);
  balloonSpots(q.options.length).forEach(([left, top], index) => {
    const balloon = el('button', `balloon tone-${index % 4}`);
    balloon.append(el('span', 'balloon-text', q.options[index]));
    balloon.style.left = `${left}%`;
    balloon.style.top = `${top}%`;
    balloon.style.animationDelay = `${index * .18}s, ${.9 + index * .18}s`;
    balloon.onclick = () => {
      if (busy) return;
      sfx('unlock');
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
          sfx('pop');
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

// Bridge: letters float as planks; the heroine crosses on a right word and falls in on a wrong one.
function renderBridgeGame() {
  const scene = el('div', 'bridge-scene');
  scene.append(el('div', 'bank left'), el('div', 'bank right'), el('div', 'river'));
  const heroine = makeHeroine(BRIDGE_POSES, 'bridge-stand', 'on-bank');
  const bridge = el('div', 'answer bridge');
  const letters = el('div', 'letters planks');
  [...state.question.letters].forEach((letter, index) => {
    const plank = el('button', '', letter);
    plank.style.animationDelay = `${(index % 5) * -.6}s`;
    plank.onclick = () => {
      if (busy || mediumChecking) return;
      sfx('plank');
      setPose(heroine, 'bridge-carry');
      clearTimeout(heroine.poseTimer);
      heroine.poseTimer = setTimeout(() => { if (!busy) setPose(heroine, 'bridge-stand'); }, 450);
      editMedium('add', index);
    };
    letters.append(plank);
  });
  scene.append(bridge, heroine, letters);
  const wrapper = el('div', 'bridge-game');
  const actions = el('div', 'actions');
  const backspace = el('button', 'secondary backspace', '⌫');
  backspace.setAttribute('aria-label', 'Backspace');
  backspace.onclick = () => { sfx('plank'); editMedium('backspace'); };
  const check = el('button', '', `🌉 ${t('check')}`);
  check.onclick = () => {
    sfx('unlock');
    checkMedium(async next => {
      const box = scene.getBoundingClientRect();
      const span = bridge.getBoundingClientRect();
      const start = heroine.getBoundingClientRect();
      const toEnd = span.right - start.left - start.width * .55;
      // Timers drive the story; the animation only paints the way between two spots.
      const move = async (x, y, duration, easing = 'linear') => {
        const from = heroine.style.translate || '0px 0px';
        heroine.style.translate = `${x}px ${y}px`;
        heroine.animate([{ translate: from }, { translate: `${x}px ${y}px` }], { duration: reducedMotion ? 1 : duration, easing });
        await wait(duration);
      };
      setPose(heroine, 'bridge-walk');
      heroine.classList.add('walking');
      if (next.feedback === 'correct') {
        await move(toEnd, 0, 1100);
        heroine.classList.remove('walking');
        setPose(heroine, 'bridge-leap');
        sfx('boing');
        await move(box.right - start.right - 6, -14, 380, 'ease-out');
        setPose(heroine, 'bridge-stand');
        sfx('chime');
        burst(scene, bridge.lastElementChild || bridge, true);
        await wait(900);
      } else {
        await move(toEnd * .45, 0, 600);
        heroine.classList.remove('walking');
        bridge.querySelectorAll('.slot').forEach((slot, index) => {
          slot.style.animationDelay = `${index * 40}ms`;
          slot.classList.add('falling');
        });
        setPose(heroine, 'bridge-fall');
        await wait(160);
        await move(toEnd * .45, box.bottom - span.bottom + 10, 380, 'ease-in');
        sfx('splash');
        scene.append(el('div', 'splash'));
        setPose(heroine, 'bridge-wet');
        await move(toEnd * .45, box.bottom - span.bottom - 30, 260, 'ease-out');
        heroine.classList.add('bobbing');
        await wait(1500);
      }
    });
  };
  actions.append(backspace, check);
  wrapper.append(scene, actions);
  return wrapper;
}

// Spell: letters fly out of the wand as runes; a right word is cast, a wrong one backfires.
function spellScene() {
  const scene = el('div', 'spell-scene');
  const heroine = makeHeroine(SPELL_POSES, 'spell-ready');
  return { scene, heroine };
}

async function castSpell(scene, heroine, runes, next, previous) {
  await wait(450);
  if (next.feedback === 'correct') {
    setPose(heroine, 'spell-success');
    runes.classList.add('success');
    sfx('chime');
    speak(previous);
    burst(scene, runes, true);
    app.querySelector('.picture-frame')?.classList.add('alive');
    await wait(1700);
  } else {
    const sneeze = Math.random() < .5;
    setPose(heroine, sneeze ? 'spell-sneeze' : 'spell-sooty');
    runes.classList.add('fizzle');
    sfx(sneeze ? 'sneeze' : 'fart');
    scene.append(el('div', sneeze ? 'sneeze-cloud' : 'smoke'));
    await wait(sneeze ? 1900 : 1700);
  }
}

function startCast(heroine, runes) {
  sfx('unlock');
  sfx('whoosh');
  setPose(heroine, 'spell-cast');
  runes.classList.add('casting');
}

function renderSpellGame(q) {
  const wrapper = el('div', 'spell-game');
  const { scene, heroine } = spellScene();
  const runes = el('div', 'runes');
  scene.append(heroine, runes);
  const input = el('input', 'answer');
  input.autocomplete = 'off'; input.autocapitalize = 'off'; input.spellcheck = false;
  input.placeholder = t('type');
  input.maxLength = 200;
  let shown = '';
  input.addEventListener('input', () => {
    const value = input.value;
    if (value.length > shown.length && value.startsWith(shown)) {
      [...value.slice(shown.length)].forEach(char => runes.append(el('span', char === ' ' ? 'rune gap' : 'rune', char)));
    } else runes.replaceChildren(...[...value].map(char => el('span', char === ' ' ? 'rune gap still' : 'rune still', char)));
    shown = value;
  });
  const cast = () => {
    if (busy) return;
    if (!input.value.trim()) { input.focus(); return; }
    startCast(heroine, runes);
    act('hard', input.value, (next, previous) => castSpell(scene, heroine, runes, next, previous));
  };
  input.addEventListener('keydown', event => { if (event.key === 'Enter') cast(); });
  const actions = el('div', 'actions');
  const castButton = el('button', '', `🪄 ${t('check')}`);
  castButton.onclick = cast;
  actions.append(castButton);
  if (q.can_skip_hard) actions.append(button(t('skip'), 'skip', null, 'secondary'));
  wrapper.append(scene, input, actions);
  return wrapper;
}

// Spell with help: the typed word was swapped for its letters; tapping them lines up the runes.
// Every saved tap redraws the screen, so the letters pop in only the first time a word is shown.
let spellLettersShown = '';
function renderSpellLettersGame(q) {
  const wrapper = el('div', 'spell-game');
  const { scene, heroine } = spellScene();
  const runes = el('div', 'answer runes');
  scene.append(heroine, runes);
  const shownKey = `${session}|${q.number}|${q.letters}`;
  const letters = el('div', spellLettersShown === shownKey ? 'letters spell-letters' : 'letters spell-letters intro');
  spellLettersShown = shownKey;
  [...q.letters].forEach((letter, index) => {
    const choice = el('button', '', letter);
    choice.style.animationDelay = `${(index % 6) * 50}ms`;
    choice.onclick = () => {
      if (busy || mediumChecking) return;
      sfx('plank');
      editMedium('add', index);
      letters.classList.remove('intro', 'nudge');
      void letters.offsetWidth;
      letters.classList.add('nudge');
    };
    letters.append(choice);
  });
  const actions = el('div', 'actions');
  const backspace = el('button', 'secondary backspace', '⌫');
  backspace.setAttribute('aria-label', 'Backspace');
  backspace.onclick = () => editMedium('backspace');
  const castButton = el('button', '', `🪄 ${t('check')}`);
  castButton.onclick = () => {
    if (busy || mediumChecking) return;
    startCast(heroine, runes);
    checkMedium((next, previous) => castSpell(scene, heroine, runes, next, previous));
  };
  actions.append(backspace, castButton);
  wrapper.append(scene, letters, actions);
  return wrapper;
}

// Game skins per question type. Add another skin to a list and questions take turns with it.
const GAME_SKINS = {
  multiple_choice: [renderBallGame],
  jumbled_letters: [renderBridgeGame],
  typed_answer: [renderSpellGame],
};

function pickSkin(q) {
  if (q.type === 'jumbled_letters' && q.hinted) return renderSpellLettersGame;
  const skins = GAME_SKINS[q.type] || [];
  return skins.length ? skins[(q.number - 1) % skins.length] : null;
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
  const skin = pickSkin(q);
  const playing = gameMode && skin !== null;
  if (skin) {
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
  const card = el('div', playing ? `card compact ${q.type}` : 'card');
  const pictureFrame = el('div', 'picture-frame');
  card.append(pictureFrame);
  loadImage(q.image_asset_id, pictureFrame);
  card.append(el('div', 'prompt', q.prompt));
  if (q.task) card.append(el('div', 'hint task', q.task));
  if (q.hint && q.hint !== q.prompt) card.append(el('div', 'hint', q.hint));
  if (q.type === 'typed_answer' && q.first_letter) card.append(el('div', 'hint', t('starts', { letter: q.first_letter })));
  app.append(card);
  if (q.type === 'jumbled_letters') {
    mediumSelected = [...q.selected];
    mediumMask = q.answer_mask.split(' ').map(slot => slot ? '_' : '').join(' ');
  }
  if (playing) {
    app.append(skin(q));
    if (q.type === 'jumbled_letters') drawMediumSelection();
  } else if (q.type === 'multiple_choice') {
    const choices = el('div', 'choices');
    q.options.forEach((option, index) => choices.append(button(option, 'easy', index)));
    app.append(choices);
  } else if (q.type === 'jumbled_letters') {
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
    voiceButton.onclick = toggleVoicePicker;
    sound.append(listenButton, voiceButton);
    const picker = el('div', 'voice-picker');
    picker.hidden = true;
    app.append(sound, el('div', 'voice-name'), picker);
    showVoiceName();
  }
  if (q.type === 'typed_answer') app.querySelector('input.answer')?.focus();
}

if (!session || !initData) showError(new Error('unauthorized'));
else refresh();
