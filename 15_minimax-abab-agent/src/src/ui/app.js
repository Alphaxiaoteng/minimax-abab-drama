/**
 * 沉浸式互动推理剧 Agent — 前端交互逻辑。
 * 纯原生 JS，零构建、零 CDN。
 * 所有 API 请求走 /api/*，静态资源由同源 serve。
 */

/* ---------- 情绪 → 中文标签（硬编码与后端一致） ---------- */
const EMOTION_LABELS = {
  calm: '平静', joyful: '欢愉', tense: '紧张',
  sorrowful: '悲恸', furious: '暴怒', fearful: '惊惧',
  suspicious: '狐疑', tender: '温柔',
};

/* ---------- 剧情阶段中文映射 ---------- */
const PHASE_LABELS = {
  intro: '开场', exploration: '探索',
  'cross-examination': '交叉质询', confrontation: '对质',
  resolution: '终局',
};

/* ---------- DOM 引用 ---------- */
const $ = (sel) => document.querySelector(sel);
const personaGrid = $('#persona-grid');
const welcome = $('#welcome');
const messages = $('#messages');
const composer = $('#composer');
const userInput = $('#user-input');
const sendBtn = $('#send-btn');
const hud = $('#hud');
const trustBar = $('#trust-bar');
const trustFill = $('#trust-fill');
const trustValue = $('#trust-value');
const tensionBar = $('#tension-bar');
const tensionFill = $('#tension-fill');
const tensionValue = $('#tension-value');
const phaseLabel = $('#phase-label');
const clueList = $('#clue-list');
const endBtn = $('#end-btn');
const errorBar = $('#error-bar');
const audioTpl = $('#reply-audio-tpl');

/* ---------- 全局状态 ---------- */
let sessionId = null;
let screenplayClues = [];
let currentPersona = null;

/* ---------- 错误提示 ---------- */
let errorTimer = null;
function showError(msg) {
  errorBar.textContent = msg;
  errorBar.hidden = false;
  clearTimeout(errorTimer);
  errorTimer = setTimeout(() => { errorBar.hidden = true; }, 6000);
}

/* ---------- API 请求 ---------- */
async function api(method, path, body) {
  const opts = { method, headers: { 'content-type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || `请求失败 (${res.status})`);
  }
  return data;
}

/* ---------- 情绪主题切换 ---------- */
function setTheme(emotion) {
  document.body.className = '';
  const cls = emotion ? `theme-${emotion}` : 'theme-calm';
  document.body.classList.add(cls);
}

/* ---------- 波形条渲染 ---------- */
function renderWaveform(container, seed) {
  const wave = container.querySelector('.waveform');
  wave.innerHTML = '';
  // 用 seed 生成确定性伪随机柱状条高度
  let h = seed >>> 0;
  const bars = 28;
  for (let i = 0; i < bars; i++) {
    h = (h * 1664525 + 1013904223) >>> 0;
    const height = 4 + (h % 18);
    const bar = document.createElement('i');
    bar.style.height = `${height}px`;
    wave.appendChild(bar);
  }
}

/* ---------- 语音条创建 ---------- */
function createAudioBar(dataUrl, mimeType, durationMs) {
  const clone = audioTpl.content.cloneNode(true);
  const bar = clone.querySelector('.voice-bar');
  const playBtn = clone.querySelector('.play-btn');
  const audio = clone.querySelector('audio');
  const duration = clone.querySelector('.duration');

  audio.src = dataUrl;
  duration.textContent = `${Math.ceil(durationMs / 1000)}s`;

  // 手动播放，绝不 autoplay
  playBtn.addEventListener('click', () => {
    if (audio.paused) {
      audio.play().catch(() => showError('浏览器阻止了音频播放，请手动允许'));
      playBtn.textContent = '⏸';
    } else {
      audio.pause();
      playBtn.textContent = '▶';
    }
  });
  audio.addEventListener('ended', () => { playBtn.textContent = '▶'; });

  return { bar, audio };
}

/* ---------- 打字机效果 ---------- */
function typewriter(el, text, speed = 40) {
  return new Promise((resolve) => {
    let i = 0;
    el.textContent = '';
    el.closest('.msg')?.classList.add('is-typing');
    const tick = () => {
      if (i < text.length) {
        el.textContent += text[i];
        i++;
        setTimeout(tick, speed);
      } else {
        el.closest('.msg')?.classList.remove('is-typing');
        resolve();
      }
    };
    tick();
  });
}

/* ---------- HUD 更新 ---------- */
function updateHUD(state) {
  if (!state) return;
  hud.hidden = false;
  trustFill.style.width = `${state.trust}%`;
  trustValue.textContent = state.trust;
  trustBar.setAttribute('aria-valuenow', String(state.trust));

  tensionFill.style.width = `${state.tension}%`;
  tensionValue.textContent = state.tension;
  tensionBar.setAttribute('aria-valuenow', String(state.tension));

  const label = PHASE_LABELS[state.phase] ?? state.phase;
  phaseLabel.textContent = `阶段：${label}`;

  // 线索列表
  clueList.innerHTML = '';
  if (state.revealedClueIds.length === 0) {
    const empty = document.createElement('li');
    empty.className = 'clue-empty';
    empty.textContent = '尚未发现线索';
    clueList.appendChild(empty);
  } else {
    for (const id of state.revealedClueIds) {
      const clue = screenplayClues.find((c) => c.id === id);
      if (!clue) continue;
      const li = document.createElement('li');
      const title = document.createElement('strong');
      title.textContent = clue.title;
      const detail = document.createElement('span');
      detail.className = 'clue-detail';
      detail.textContent = clue.detail;
      li.append(title, detail);
    }
  }
}

/* ---------- 添加消息气泡 ---------- */
function appendMessage(role, text, emotion, audioData) {
  const msg = document.createElement('div');
  msg.className = `msg ${role}`;

  const who = document.createElement('span');
  who.className = 'who';
  who.textContent = role === 'user' ? '你' : (currentPersona?.name ?? '人物');

  const bubble = document.createElement('div');
  bubble.className = 'bubble';

  if (emotion) {
    const chip = document.createElement('span');
    chip.className = 'emotion-chip';
    chip.textContent = EMOTION_LABELS[emotion] ?? emotion;
    bubble.appendChild(chip);
  }

  const textNode = document.createElement('span');
  textNode.textContent = role === 'user' ? text : '';
  bubble.appendChild(textNode);
  msg.appendChild(who);
  msg.appendChild(bubble);

  // 语音条
  if (audioData) {
    const { bar } = createAudioBar(audioData.dataUrl, audioData.mimeType, audioData.durationMs);
    renderWaveform(bar, audioData.durationMs);
    msg.appendChild(bar);
  }

  messages.appendChild(msg);
  msg.scrollIntoView({ behavior: 'smooth', block: 'end' });

  // persona 消息用打字机渲染
  if (role === 'persona' && text.length > 0) {
    return typewriter(textNode, text);
  }
  return Promise.resolve();
}

/* ---------- 开始会话 ---------- */
async function startSession(persona) {
  currentPersona = persona;
  welcome.classList.add('hidden');
  messages.hidden = false;
  composer.hidden = false;
  messages.innerHTML = '';

  try {
    const resp = await api('POST', '/api/session', { personaId: persona.id });
    sessionId = resp.sessionId;
    setTheme(resp.opening.turn?.emotion);
    updateHUD(resp.state);
    await appendMessage('persona', persona.openingLine, resp.opening.turn?.emotion ?? null, resp.opening.speech);
    userInput.focus();
  } catch (err) {
    showError(err.message);
  }
}

/* ---------- 发送对话 ---------- */
async function sendTurn(text) {
  if (!sessionId) return;
  await appendMessage('user', text, null, null);
  sendBtn.disabled = true;

  try {
    const resp = await api('POST', '/api/turn', { sessionId, text });
    setTheme(resp.turn?.emotion);
    updateHUD(resp.state);
    await appendMessage('persona', resp.turn.text, resp.turn.emotion, resp.speech);

    if (resp.state.ended) {
      composer.hidden = true;
      showError('本场戏已结束，点击「散场」重选人物');
    }
  } catch (err) {
    showError(err.message);
  } finally {
    sendBtn.disabled = false;
    userInput.focus();
  }
}

/* ---------- 散场 ---------- */
function endSession() {
  sessionId = null;
  currentPersona = null;
  hud.hidden = true;
  messages.hidden = true;
  messages.innerHTML = '';
  composer.hidden = true;
  welcome.classList.remove('hidden');
  personaGrid.querySelectorAll('.persona-card').forEach((c) => c.classList.remove('active'));
  setTheme('calm');
}

/* ---------- 初始化 ---------- */
async function init() {
  try {
    const [personasData, screenplayData] = await Promise.all([
      api('GET', '/api/personas'),
      api('GET', '/api/screenplay'),
    ]);
    screenplayClues = screenplayData.screenplay.clues;

    personaGrid.innerHTML = '';
    for (const p of personasData.personas) {
      const card = document.createElement('button');
      card.className = 'persona-card';
      card.type = 'button';
      card.setAttribute('role', 'listitem');
      card.setAttribute('aria-label', `选择 ${p.name}：${p.tagline}`);
      // 人物数据一律走 textContent 注入，绝不拼 innerHTML（防 XSS）
      const pname = document.createElement('span'); pname.className = 'p-name'; pname.textContent = p.name;
      const ptag = document.createElement('span'); ptag.className = 'p-tag'; ptag.textContent = p.tagline;
      const pline = document.createElement('span'); pline.className = 'p-line'; pline.textContent = p.openingLine;
      card.append(pname, ptag, pline);
      card.addEventListener('click', () => {
        if (sessionId) return;
        personaGrid.querySelectorAll('.persona-card').forEach((c) => c.classList.remove('active'));
        card.classList.add('active');
        void startSession(p);
      });
      personaGrid.appendChild(card);
    }
  } catch (err) {
    showError(`加载失败：${err.message}`);
  }
}

/* ---------- 事件绑定 ---------- */
composer.addEventListener('submit', (e) => {
  e.preventDefault();
  const text = userInput.value.trim();
  if (text.length === 0) return;
  userInput.value = '';
  void sendTurn(text);
});

endBtn.addEventListener('click', endSession);

/* ---------- 启动 ---------- */
void init();