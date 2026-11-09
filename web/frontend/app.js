(() => {
  'use strict';
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const TOKEN_KEY = 'motrack_vip_token';
  const API_VERSION = 5;
  const DURATIONS = [10, 15, 20, 30, 45, 60];
  const STYLE_KEYS = ['pace', 'transition', 'look', 'zoom', 'music', 'slow_motion'];
  const PRESETS = [
    { id: 'hype', cls: 'p-hype', emo: '🔥', name: '燃炸快剪', desc: '热血配乐·闪白·卡点',
      style: { pace: 'tight', transition: 'flash', look: 'vivid', zoom: true, music: 'hype', slow_motion: true } },
    { id: 'cinema', cls: 'p-cinema', emo: '🎬', name: '电影大片', desc: '宽银幕·推镜·慢动作',
      style: { pace: 'relaxed', transition: 'fade', look: 'cinematic', zoom: true, music: 'chill', slow_motion: true } },
    { id: 'street', cls: 'p-street', emo: '🎤', name: '街头嘻哈', desc: '嘻哈律动·硬切',
      style: { pace: 'standard', transition: 'cut', look: 'vivid', zoom: false, music: 'groove', slow_motion: false } },
    { id: 'retro', cls: 'p-retro', emo: '📼', name: '复古胶片', desc: '胶片调色·律动',
      style: { pace: 'standard', transition: 'fade', look: 'retro', zoom: false, music: 'groove', slow_motion: false } },
    { id: 'bw', cls: 'p-bw', emo: '🖤', name: '黑白经典', desc: '黑白·舒缓·推镜',
      style: { pace: 'relaxed', transition: 'fade', look: 'bw', zoom: true, music: 'chill', slow_motion: true } },
    { id: 'raw', cls: 'p-raw', emo: '🏀', name: '原汁原味', desc: '保留现场声·不加特效',
      style: { pace: 'standard', transition: 'fade', look: 'vivid', zoom: false, music: 'none', slow_motion: false } }
  ];
  // Progress steps shown on the player while a job runs; stage -> step index.
  const FLOWS = {
    lightweight: { steps: ['看比赛', '挑镜头', '剪辑渲染'],
                   at: { QUEUED: 0, ANALYZING: 0, LOCAL_AGENT_RUNNING: 1, RENDERING: 2, OUTPUT_VERIFIED: 3 } },
    ai: { steps: ['看比赛', 'AI 看画面', '剪辑渲染', '写解说'],
          at: { QUEUED: 0, ANALYZING: 0, AI_EDITING: 1, AI_LOOKING: 1, RENDERING: 2, AI_WRITING: 3, OUTPUT_VERIFIED: 4 } }
  };
  const STAGE_TEXT = {
    QUEUED: '排队中…', ANALYZING: '第一次处理这段视频，正在看比赛…', LOCAL_AGENT_RUNNING: '正在挑选精彩镜头…',
    AI_EDITING: 'AI 剪辑师开始工作…', AI_LOOKING: 'AI 正在看画面，挑真正精彩的镜头…', RENDERING: '正在剪辑、加配乐和特效…',
    AI_WRITING: 'AI 正在写解说…', OUTPUT_VERIFIED: '剪好了'
  };
  const SUGGEST = {
    lightweight: ['缩短到 10 秒', '换一首', '改成竖屏', '只保留 3 段', '做成电影感', '加特效'],
    ai: ['把没看点的镜头去掉', '最精彩的是哪一球？', '只要后半段', '改成竖屏，节奏快一点', '换成复古，配乐换嘻哈', '标题改成“街球之夜”']
  };

  const state = { videos: [], video: null, mode: 'lightweight', vip: false, dev: false, duration: 20,
                  preset: 'hype', sessionId: '', busy: false, output: null, events: [],
                  music: 'hype', musicList: [], titleOff: false, pane: 'edit' };

  const store = {
    get() { try { return localStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; } },
    set(v) { try { v ? localStorage.setItem(TOKEN_KEY, v) : localStorage.removeItem(TOKEN_KEY); } catch (e) { /* private mode */ } }
  };
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const clock = (s) => { s = Math.max(0, Number(s) || 0); return Math.floor(s / 60) + ':' + String(Math.floor(s % 60)).padStart(2, '0'); };
  const frameUrl = (t) => '/api/v1/videos/' + state.video.id + '/frame?t=' + Math.max(0, Math.min(t, (state.video.duration || 1) - 0.1)).toFixed(1);
  const artifactUrl = (path, bust) => '/api/v1/artifact?path=' + encodeURIComponent(path) + (bust ? '&v=' + Date.now() : '');
  const narrow = () => window.matchMedia('(max-width: 899px)').matches;
  // <img> inside a shimmering placeholder; a failed load leaves a clean gradient.
  const img = (url) => '<img loading="lazy" decoding="async" alt="" src="' + esc(url) + '" onload="this.parentNode.classList.add(\'ok\')" onerror="this.parentNode.classList.add(\'bad\')">';

  class ApiError extends Error { constructor(message, status, code) { super(message); this.status = status; this.code = code; } }
  async function api(path, body) {
    const headers = {};
    const token = store.get();
    if (token) headers['X-VIP-Token'] = token;
    if (body) headers['Content-Type'] = 'application/json';
    let res;
    try { res = await fetch(path, { method: body ? 'POST' : 'GET', headers, body: body ? JSON.stringify(body) : undefined }); }
    catch (e) { throw new ApiError('连不上 MoTrack，请确认程序还在运行', 0); }
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) { location.href = '/app/login.html'; throw new ApiError('请先登录', 401); }
    if (!res.ok) {
      const d = data.detail;
      throw new ApiError(typeof d === 'string' ? d : (d && d.message) || '出了点问题，请稍后重试', res.status, d && d.code);
    }
    return data;
  }

  let toastTimer = 0;
  function toast(text, bad) {
    const el = $('#toast');
    el.textContent = text; el.className = 'toast show' + (bad ? ' bad' : '');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { el.className = 'toast' + (bad ? ' bad' : ''); }, 3800);
  }
  /* ---------- busy + working overlay ---------- */
  function setBusy(v) {
    state.busy = v;
    $('#go').disabled = v; $('#send').disabled = v;
    $$('.vcard').forEach((b) => { b.disabled = v; });
    $('#go').textContent = v ? '剪辑中…' : (state.output ? '重新剪辑' : '开始剪辑');
  }
  // stage: a job stage key, 'CHAT' for an edit from the chat, or null to hide.
  function working(stage, pct) {
    const box = $('#working');
    box.classList.toggle('hidden', stage == null);
    if (stage == null) return;
    const flow = FLOWS[state.mode];
    const at = stage === 'CHAT' ? -1 : (flow.at[stage] != null ? flow.at[stage] : 0);
    $('#wsteps').innerHTML = stage === 'CHAT' ? '' : flow.steps.map((s, i) =>
      '<li class="' + (i < at ? 'done' : i === at ? 'now' : '') + '">' + (i < at ? '✓ ' : '') + esc(s) + '</li>').join('');
    $('#workingText').textContent = stage === 'CHAT'
      ? (state.mode === 'ai' ? 'AI 剪辑师正在按你说的改…' : '正在按你说的改…') : (STAGE_TEXT[stage] || '处理中…');
    $('#workingSub').textContent = stage === 'AI_LOOKING' ? '会跳过观众、广告和没看点的镜头' : '';
    const bar = $('#workingBar');
    if (typeof pct === 'number') { bar.classList.add('fixed'); bar.style.width = Math.max(4, pct) + '%'; }
    else { bar.classList.remove('fixed'); bar.style.width = ''; }
  }

  /* ---------- top steps ---------- */
  function renderSteps() {
    const now = state.busy ? 2 : state.output ? 3 : state.video ? 1 : 0;
    $$('#steps li').forEach((li, i) => { li.className = i < now ? 'done' : i === now ? 'now' : ''; });
  }

  /* ---------- videos ---------- */
  const UPLOAD_STAGE = { uploading: '上传中', TRANSCODING: '转换格式', ANALYZING: '找精彩镜头' };
  function renderVideos() {
    const upload = '<button class="vcard upload" id="uploadCard" type="button"><div class="thumb">＋</div>' +
      '<div><b>上传视频</b><small>从相册选一段比赛</small></div></button>';
    $('#videos').innerHTML = upload + state.videos.map((v) => {
      const del = v.upload ? '<span class="del" data-del="' + esc(v.id) + '" role="button" aria-label="删除" title="删除">×</span>' : '';
      if (v.status && v.status !== 'ready') {
        const failed = v.status === 'failed';
        const label = failed ? (v.error || '处理失败') : (UPLOAD_STAGE[v.stage] || UPLOAD_STAGE[v.status] || '处理中') + ' ' + (v.progress || 0) + '%';
        return '<div class="vcard pending' + (failed ? ' failed' : '') + '"><div class="thumb ph"></div><div><b>' + esc(v.name) + '</b><small>' + esc(label) + '</small>' +
          (failed ? '' : '<div class="bar"><i style="width:' + (v.progress || 0) + '%"></i></div>') + '</div>' + (failed ? del : '') + '</div>';
      }
      return '<button class="vcard' + (state.video && state.video.id === v.id ? ' active' : '') + '" data-id="' + esc(v.id) + '" type="button">' +
        '<div class="thumb ph">' + img(v.poster) + '<span class="dur">' + clock(v.duration) + '</span></div>' +
        '<div><b>' + esc(v.name) + '</b><small>' + esc(v.subtitle || '') + '</small></div>' + del + '</button>';
    }).join('');
  }
  let videoPoll = 0;
  async function loadVideos(selectId) {
    try { state.videos = await api('/api/v1/videos'); } catch (e) { toast(e.message, true); return; }
    const ready = state.videos.filter((v) => v.status === 'ready');
    if (state.video && !ready.some((v) => v.id === state.video.id)) state.video = null;
    renderVideos();
    const want = selectId && ready.find((v) => v.id === selectId);
    if (want) selectVideo(want.id); else if (!state.video && ready.length) selectVideo(ready[0].id);
    clearTimeout(videoPoll);
    if (state.videos.some((v) => v.status && !['ready', 'failed'].includes(v.status))) videoPoll = setTimeout(pollUploads, 1500);
  }
  async function pollUploads() {
    const before = new Set(state.videos.filter((v) => v.status === 'ready').map((v) => v.id));
    try { state.videos = await api('/api/v1/videos'); } catch (e) { return; }
    renderVideos();
    const fresh = state.videos.find((v) => v.status === 'ready' && v.upload && !before.has(v.id));
    if (fresh && !state.busy) { selectVideo(fresh.id); toast('「' + fresh.name + '」处理好了，可以开始剪了 🎉'); }
    if (state.videos.some((v) => v.status && !['ready', 'failed'].includes(v.status))) videoPoll = setTimeout(pollUploads, 1500);
  }
  async function uploadVideo(file) {
    if (!file) return;
    if (file.size > 1024 * 1024 * 1024) { toast('视频不能超过 1GB', true); return; }
    let uid;
    try {
      const started = await api('/api/v1/uploads', { name: file.name || 'video.mp4', size: file.size });
      uid = started.id;
      const chunk = started.chunk || 8 * 1024 * 1024;
      state.videos.unshift({ id: uid, name: file.name || '我的视频', upload: true, status: 'uploading', progress: 0 });
      renderVideos();
      let offset = 0, tries = 0;
      while (offset < file.size) {
        const piece = file.slice(offset, Math.min(file.size, offset + chunk));
        let res;
        try { res = await fetch('/api/v1/uploads/' + uid + '?offset=' + offset, { method: 'PUT', body: piece }); }
        catch (e) { res = null; }
        if (res && res.status === 409) { offset = (await res.json()).expected; continue; }  // resume where the server is
        if (!res || !res.ok) {
          if (++tries > 4) throw new ApiError('网络不稳定，上传中断了，请重试', 0);
          await new Promise((r) => setTimeout(r, 1500 * tries)); continue;
        }
        tries = 0; offset = (await res.json()).received;
        const v = state.videos.find((x) => x.id === uid);
        if (v) { v.progress = Math.round(100 * offset / file.size); renderVideos(); }
      }
      await api('/api/v1/uploads/' + uid + '/finish', {});
      toast('上传好了，正在转换格式、找精彩镜头…');
      loadVideos();
    } catch (e) {
      toast(e.message || '上传失败', true);
      loadVideos();
    }
    $('#videoFile').value = '';
  }
  async function deleteVideo(id) {
    const v = state.videos.find((x) => x.id === id);
    if (!v || !confirm('删除「' + v.name + '」？剪好的集锦也会一起删除。')) return;
    try {
      const res = await fetch('/api/v1/videos/' + encodeURIComponent(id), { method: 'DELETE' });
      if (!res.ok) throw new Error(((await res.json().catch(() => ({}))).detail) || '删除失败');
      if (state.video && state.video.id === id) state.video = null;
      toast('已删除'); loadVideos();
    } catch (e) { toast(e.message, true); }
  }
  function selectVideo(id) {
    const v = state.videos.find((x) => x.id === id);
    if (!v || state.busy) return;
    state.video = v;
    renderVideos();
    $('#source').src = v.source || ('/api/v1/videos/' + encodeURIComponent(v.id) + '/source');
    if (v.poster) $('#source').poster = v.poster;
    resetOutput(); resetChat(); renderDurations(); loadMoments(); renderSteps();
  }

  /* ---------- duration ---------- */
  function maxDuration() { return Math.max(5, Math.min(60, Math.floor((state.video && state.video.duration) || 60))); }
  function renderDurations() {
    const max = maxDuration();
    if (state.duration > max) state.duration = max;
    const list = DURATIONS.filter((d) => d < max);
    if (!list.includes(max)) list.push(max);
    $('#durations').innerHTML = list.map((d) =>
      '<button class="chip' + (d === state.duration ? ' active' : '') + '" data-d="' + d + '" type="button">' +
      (d === max && !DURATIONS.includes(d) ? '整段 ' : '') + d + ' 秒</button>').join('');
    $('#durationHint').textContent = max < 60 ? '这段原片只有 ' + clock(state.video.duration) + '，最长剪 ' + max + ' 秒' : '';
  }

  /* ---------- style ---------- */
  function segValue(id) { const b = $('#' + id + ' button.active'); return b ? b.dataset.value : ''; }
  function setSeg(id, value) {
    const buttons = $$('#' + id + ' button');
    const match = buttons.find((b) => b.dataset.value === value);
    if (match) buttons.forEach((b) => b.classList.toggle('active', b === match));
  }
  function controlsStyle() {
    return { pace: segValue('pace'), transition: segValue('transition'), look: segValue('look'),
             zoom: $('#zoom').checked, music: state.music, slow_motion: $('#slowmo').checked };
  }
  function editStyle() {
    const title = $('#title').value.trim();
    return { ...controlsStyle(), captions: $('#captions').checked, aspect: segValue('aspect'),
             title: title || (state.titleOff ? '' : null) };
  }
  function renderPresets() {
    $('#presets').innerHTML = PRESETS.map((p) =>
      '<button class="preset ' + p.cls + (state.preset === p.id ? ' active' : '') + '" data-id="' + p.id + '" type="button">' +
      '<span class="emo">' + p.emo + '</span><b>' + esc(p.name) + '</b><small>' + esc(p.desc) + '</small></button>').join('');
    $('#customNote').classList.toggle('hidden', state.preset !== 'custom');
  }
  function applyPreset(id) {
    const p = PRESETS.find((x) => x.id === id); if (!p) return;
    const s = p.style;
    setSeg('pace', s.pace); setSeg('transition', s.transition); setSeg('look', s.look);
    $('#zoom').checked = s.zoom; $('#slowmo').checked = s.slow_motion;
    state.music = s.music; state.preset = id;
    renderMusic(); renderPresets();
  }
  function matchPreset() {
    const cur = controlsStyle();
    const hit = PRESETS.find((p) => STYLE_KEYS.every((k) => p.style[k] === cur[k]));
    state.preset = hit ? hit.id : 'custom';
    renderPresets();
  }
  // The style the editor actually used; mirroring it keeps chat edits from being undone.
  function applyStyle(s) {
    if (!s || typeof s !== 'object') return;
    setSeg('pace', s.pace); setSeg('transition', s.transition); setSeg('look', s.look); setSeg('aspect', s.aspect);
    if (typeof s.captions === 'boolean') $('#captions').checked = s.captions;
    if (typeof s.slow_motion === 'boolean') $('#slowmo').checked = s.slow_motion;
    if (typeof s.zoom === 'boolean') $('#zoom').checked = s.zoom;
    if (typeof s.music === 'string') state.music = s.music;
    if ('title' in s) { state.titleOff = s.title === ''; $('#title').value = s.title || ''; }
    renderMusic(); matchPreset();
  }
  function styleText(s) {
    if (!s) return '';
    const preset = PRESETS.find((p) => STYLE_KEYS.every((k) => p.style[k] === s[k]));
    const bits = [preset ? preset.emo + ' ' + preset.name : '自定义风格'];
    if (s.aspect === '9:16') bits.push('竖屏');
    if (s.music && s.music !== 'none') bits.push('♪ ' + musicTitle(s.music));
    return bits.join(' · ');
  }
  /* ---------- music ---------- */
  function musicTitle(id) {
    const m = state.musicList.find((x) => x.id === id);
    return m ? m.title : (id && id.startsWith('upload:') ? '我的音乐' : '配乐');
  }
  function renderMusic() {
    const items = [{ id: 'none', title: '原声' }, ...state.musicList];
    $('#music').innerHTML = items.map((m) =>
      '<button class="chip' + (m.id === state.music ? ' active' : '') + '" data-id="' + esc(m.id) + '" type="button" title="' + esc(m.desc || m.title) + '">' +
      (m.id.startsWith('upload:') ? '🎵 ' : '') + esc(m.title) + '</button>').join('');
    $('#musicPreview').disabled = state.music === 'none';
    $('#musicHint').textContent = state.music === 'none' ? '内置配乐会自动卡点'
      : state.music.startsWith('upload:') ? '用你的音乐，原声调低' : '已开卡点：每一刀落在鼓点上';
  }
  async function loadMusic() {
    try {
      const data = await api('/api/v1/music');
      state.musicList = [...(data.presets || []), ...(data.uploads || [])];
    } catch (e) { state.musicList = []; }
    renderMusic();
  }
  function stopPreview() { const a = $('#musicAudio'); if (!a.paused) a.pause(); $('#musicPreview').textContent = '▶ 试听'; }
  function previewMusic() {
    const audio = $('#musicAudio');
    if (!audio.paused) { stopPreview(); return; }
    if (state.music === 'none') return;
    audio.src = '/api/v1/music/' + encodeURIComponent(state.music) + '/preview';
    audio.play().then(() => { $('#musicPreview').textContent = '⏸ 停止'; }).catch(() => toast('试听失败，请稍后重试', true));
  }
  async function uploadMusic(file) {
    if (!file) return;
    if (file.size > 30 * 1024 * 1024) { toast('音乐文件不能超过 30MB', true); return; }
    const form = new FormData(); form.append('file', file);
    toast('正在上传音乐…');
    try {
      const res = await fetch('/api/v1/music/upload', { method: 'POST', body: form });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '上传失败');
      await loadMusic();
      state.music = data.id; renderMusic(); matchPreset();
      toast('已添加「' + data.title + '」，下次剪辑会用它做配乐');
    } catch (e) { toast(e.message, true); }
    $('#musicFile').value = '';
  }

  /* ---------- mode / VIP ---------- */
  function renderMode() {
    const ai = state.mode === 'ai';
    $$('.mode').forEach((b) => b.classList.toggle('active', b.dataset.mode === state.mode));
    $('#aiLock').classList.toggle('hidden', state.vip);
    $('#go').classList.toggle('vip', ai);
    $('#goHint').textContent = ai ? 'AI 先看画面再剪，约 30–60 秒' : '约 5 秒出片';
    $('#avatar').textContent = ai ? '👑' : '🤖';
    $('#avatar').classList.toggle('vip', ai);
    $('#assistantName').textContent = ai ? 'AI 剪辑师' : '剪辑助手';
    $('#assistantSub').textContent = ai ? '会看画面，随便说' : '一句话告诉我怎么改';
    $('#suggest').innerHTML = SUGGEST[state.mode].map((t) => '<button type="button">' + esc(t) + '</button>').join('');
    const pill = $('#vipPill');
    pill.classList.toggle('on', state.vip);
    pill.innerHTML = state.dev ? '👑 VIP<span class="long"> · 开发模式</span>' : state.vip ? '👑 VIP<span class="long"> 会员</span>' : '👑 <span class="long">开通 </span>VIP';
  }
  function setMode(mode) {
    if (mode === state.mode || state.busy) return;
    if (mode === 'ai' && !state.vip) { openVip(); return; }
    state.mode = mode;
    renderMode(); resetChat(); loadMoments();
  }
  function openVip() {
    if (state.vip) { toast(state.dev ? '开发模式下所有人都是 VIP，直接用 AI 剪辑师吧' : '你已经是 VIP 会员'); return; }
    $('#vipDialog').classList.remove('hidden');
    setTimeout(() => $('#vipCode').focus(), 50);
  }
  function closeVip() { $('#vipDialog').classList.add('hidden'); }
  async function activate() {
    const code = $('#vipCode').value.trim();
    if (!code) { $('#vipCode').focus(); return; }
    $('#vipActivate').disabled = true;
    try {
      const r = await api('/api/v1/vip/activate', { code });
      store.set(r.token); state.vip = true;
      closeVip(); $('#vipCode').value = '';
      state.mode = 'ai'; renderMode(); resetChat(); loadMoments();
      toast('🎉 VIP 已开通，AI 剪辑师为你服务');
    } catch (e) { toast(e.message, true); }
    finally { $('#vipActivate').disabled = false; }
  }
  function lostVip() {
    store.set(''); state.vip = false;
    if (state.mode === 'ai') { state.mode = 'lightweight'; resetChat(); }
    renderMode();
  }
  async function checkVip() {
    try { const r = await api('/api/v1/vip/status'); state.vip = !!r.vip; state.dev = !!r.dev; } catch (e) { return; }
    if (!state.vip && store.get()) store.set('');
    if (state.vip) state.mode = 'ai';
  }
  async function checkBackend() {
    try { if (((await api('/api/v1/health')).api || 0) < API_VERSION) $('#staleBanner').classList.remove('hidden'); }
    catch (e) { /* the videos call reports a dead backend */ }
  }

  /* ---------- panes ---------- */
  function showPane(name) {
    state.pane = name;
    $$('.tabs button').forEach((b) => b.classList.toggle('active', b.dataset.pane === name));
    $$('.pane').forEach((p) => p.classList.toggle('active', p.id === 'pane-' + name));
    document.body.classList.toggle('chatting', name === 'chat');
    if (name === 'chat') { $('#chatDot').classList.add('hidden'); scrollLog(); }
  }
  function chatVisible() { return state.pane === 'chat' || window.matchMedia('(min-width: 1360px)').matches; }
  /* ---------- moments ---------- */
  async function loadMoments() {
    const video = state.video; if (!video) return;
    try {
      const data = await api('/api/v1/videos/' + video.id + '/events?mode=' + state.mode);
      if (video !== state.video) return;
      state.events = Array.isArray(data.events) ? data.events : [];
    } catch (e) { state.events = []; }
    renderMoments();
  }
  function momentScore(e) {
    const raw = Number(e.confidence != null ? e.confidence : (e.final_ranking_score != null ? e.final_ranking_score : e.raw_model_score)) || 0;
    return e.ai ? 0.35 * raw + 0.65 * (e.ai.highlight / 5) : raw;
  }
  function renderMoments() {
    const pool = state.events.filter((e) => !(e.ai && e.ai.basketball === false));
    const top = pool.slice().sort((a, b) => momentScore(b) - momentScore(a)).slice(0, 10)
      .sort((a, b) => Number(a.start_time) - Number(b.start_time));
    const reviewed = state.events.filter((e) => e.ai).length;
    $('#momentsNote').textContent = !top.length ? '点一下在原片里看'
      : (reviewed ? 'AI 看过 ' + reviewed + ' 个 · ' : '') + '共 ' + pool.length + ' 个，点一下在原片里看';
    if (!top.length) {
      $('#moments').innerHTML = '<div class="none">第一次剪辑时会自动找出精彩瞬间。</div>';
      return;
    }
    $('#moments').innerHTML = top.map((e) => {
      const mid = (Number(e.start_time) + Number(e.end_time || e.start_time)) / 2;
      const s = momentScore(e);
      const stars = s >= 0.6 ? '★★★' : s >= 0.35 ? '★★☆' : '★☆☆';
      const name = e.ai ? (e.ai.action === '庆祝' ? '庆祝时刻' : e.ai.action === '其他' ? '篮球动作' : '疑似' + e.ai.action) : (e.display_name || '精彩动作');
      return '<button class="moment" data-t="' + Number(e.start_time) + '" type="button">' +
        '<div class="pic ph">' + img(frameUrl(mid)) + '<span class="time">' + clock(e.start_time) + '</span>' +
        (e.ai ? '<span class="ai-tag">AI 看过</span>' : '') + '</div>' +
        '<div class="info"><b>' + esc(name) + '</b><span class="stars">' + stars + '</span>' +
        (e.ai && e.ai.note ? '<span class="note">' + esc(e.ai.note) + '</span>' : '') + '</div></button>';
    }).join('');
  }

  /* ---------- output ---------- */
  function showView(view) {
    $$('#viewToggle button').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
    const hl = view === 'highlight';
    $('#highlight').classList.toggle('hidden', !hl); $('#source').classList.toggle('hidden', hl);
    (hl ? $('#source') : $('#highlight')).pause();
    $('#empty').classList.toggle('hidden', !hl || !!state.output);
  }
  function resetOutput() {
    state.output = null;
    $('#highlight').removeAttribute('src'); $('#highlight').load();
    ['#result', '#commentary', '#film', '#viewToggle'].forEach((s) => $(s).classList.add('hidden'));
    showView('highlight'); setBusy(state.busy); renderSteps();
  }
  function adoptOutput(out) {
    if (!out || !out.path) return;
    state.output = out;
    const url = artifactUrl(out.path, true);
    $('#highlight').src = url; $('#download').href = url + '&dl=1';
    prepareShare(url);
    $('#viewToggle').classList.remove('hidden');
    showView('highlight');
    $('#highlight').play().catch(() => {});
    const segs = Array.isArray(out.segments) ? out.segments : [];
    $('#resultBadge').textContent = (Number(out.duration) || 0).toFixed(1) + ' 秒 · ' + segs.filter((s) => !s.replay).length + ' 段';
    $('#resultStyle').textContent = styleText(out.edit_style);
    $('#result').classList.remove('hidden');
    const c = (out.commentary || '').trim();
    $('#commentary').classList.toggle('hidden', !c); $('#commentaryText').textContent = c;
    renderFilm(segs);
    if (!chatVisible()) $('#chatDot').classList.remove('hidden');
    setBusy(state.busy); renderSteps();
    if (narrow()) $('.player').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  function renderFilm(segs) {
    $('#film').classList.toggle('hidden', !segs.length);
    if (!segs.length) return;
    $('#filmMeta').textContent = segs.some((s) => s.replay) ? '含慢动作回放' : '';
    let n = 0;
    $('#filmTrack').innerHTML = segs.map((s) => {
      const label = s.replay ? '慢动作' : '第 ' + (++n) + ' 段';
      const at = Number(s.source_start) + Math.min(1, (Number(s.source_end) - Number(s.source_start)) / 2);
      return '<button class="seg-item ph" data-out="' + Number(s.output_start) + '" type="button" ' +
        'title="' + esc((s.label || '') + ' · 原片 ' + clock(s.source_start)) + '" ' +
        'style="flex-grow:' + Math.max(0.5, Number(s.output_duration) || 1) + '">' + img(frameUrl(at)) +
        '<span>' + label + '</span></button>';
    }).join('');
    $$('#filmTrack .seg-item').forEach((b, i) => b.classList.toggle('replay', !!segs[i].replay));
  }
  /* ---------- generate ---------- */
  async function pollJob(id) {
    for (let i = 0; i < 600; i++) {  // up to ~8 minutes for a first-time scan
      const job = await api('/api/v1/jobs/' + id);
      if (job.status === 'completed') return job;
      if (job.status === 'failed') throw new ApiError((job.error && job.error.message) || '这次没剪成，请稍后重试', 500);
      working(job.stage, job.stage === 'ANALYZING' && typeof job.progress === 'number' ? job.progress : null);
      await new Promise((r) => setTimeout(r, 700));
    }
    throw new ApiError('等待时间太长了，请稍后重试', 504);
  }
  async function generate() {
    if (state.busy || !state.video) return;
    stopPreview(); setBusy(true); renderSteps(); working('QUEUED');
    if (narrow()) $('.player').scrollIntoView({ behavior: 'smooth', block: 'start' });
    try {
      const shots = segValue('focus') === 'shots';
      const submitted = await api('/api/v1/highlights', {
        video_id: state.video.id, mode: state.mode, target_duration: state.duration,
        event_types: shots ? ['shot_attempt'] : ['basketball_action_candidate', 'dunk', 'dribble'],
        edit_style: editStyle()
      });
      const job = await pollJob(submitted.id);
      const result = job.result || {};
      state.sessionId = result.session_id || submitted.session_id || state.sessionId;
      applyStyle(result.edit_style);
      working(null);
      adoptOutput(result.output);
      const out = result.output || {};
      addMsg('agent', state.mode === 'ai'
        ? '集锦剪好了，解说在视频下面。想改就直接说，比如“把没看点的去掉”“改成竖屏”。'
        : '剪好了：' + (Number(out.duration) || 0).toFixed(1) + ' 秒。想调整可以说“缩短到 10 秒”“换一首”。');
      toast(out.duration_note || '集锦剪好了 🎉 可以播放、下载，或者在对话里继续改');
      loadMoments();
    } catch (e) {
      if (e.code === 'VIP_REQUIRED') { lostVip(); openVip(); } else toast(e.message, true);
    } finally {
      working(null); setBusy(false); renderSteps();
    }
  }

  /* ---------- chat ---------- */
  function scrollLog() { const b = $('#pane-chat .pane-body'); b.scrollTop = b.scrollHeight; }
  function addMsg(role, text, extra) {
    const el = document.createElement('div');
    el.className = 'msg ' + role;
    el.innerHTML = esc(text).replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>') + (extra || '');
    $('#log').appendChild(el); scrollLog();
    return el;
  }
  function resetChat() {
    state.sessionId = '';
    $('#log').innerHTML = '';
    addMsg('agent', state.mode === 'ai'
      ? '嗨，我是你的 AI 剪辑师 👑 我会先看画面再挑镜头。\n先点“开始剪辑”，或者直接告诉我想要什么，比如“来个 20 秒竖屏扣篮集锦”。'
      : '你好！先选个风格点“开始剪辑”，剪完可以在这里继续改，比如“缩短到 10 秒”“换一首”“改成竖屏”。');
  }
  async function send(preset) {
    if (state.busy || !state.video) return;
    const text = (preset || $('#msg').value).trim();
    if (!text) return;
    addMsg('user', text);
    $('#msg').value = ''; $('#msg').style.height = '';
    stopPreview(); setBusy(true);
    const typing = addMsg('agent', '');
    typing.innerHTML = '<span class="typing"><span></span><span></span><span></span></span>';
    const slow = setTimeout(() => working('CHAT'), 1500);  // quick answers skip the overlay
    try {
      const r = await api('/api/v1/chat', {
        message: text, session_id: state.sessionId || undefined, video_id: state.video.id,
        mode: state.mode, edit_style: editStyle()
      });
      typing.remove();
      state.sessionId = r.session_id || state.sessionId;
      applyStyle(r.edit_style);
      addMsg('agent', r.reply || '好了。', r.output ? '<br><button class="play" type="button" data-play="1">▶ 看新版本</button>' : '');
      if (r.output) {
        working(null); adoptOutput(r.output);
        if (r.output.duration_note) toast(r.output.duration_note);
      }
      if (r.output || r.events || state.mode === 'ai') loadMoments();
    } catch (e) {
      typing.remove();
      if (e.code === 'VIP_REQUIRED') { lostVip(); openVip(); addMsg('system', 'AI 剪辑师需要 VIP，已切回基础剪辑。'); }
      else addMsg('system', e.message);
    } finally {
      clearTimeout(slow); working(null); setBusy(false);
    }
  }
  /* ---------- share / save to album ---------- */
  // Fetch the reel ahead of time: iOS only opens the share sheet if share()
  // runs right inside the tap, with no download in between.
  let shareFile = null, shareFor = '';
  function prepareShare(url) {
    shareFile = null; shareFor = url;
    const btn = $('#share');
    btn.classList.add('hidden');
    if (!navigator.canShare || !window.matchMedia('(pointer: coarse)').matches) return;
    fetch(url).then((r) => r.ok ? r.blob() : Promise.reject()).then((blob) => {
      if (shareFor !== url) return;
      const file = new File([blob], 'MoTrack集锦.mp4', { type: 'video/mp4' });
      if (navigator.canShare({ files: [file] })) { shareFile = file; btn.classList.remove('hidden'); }
    }).catch(() => {});
  }
  async function share() {
    if (!shareFile) return;
    try {
      await navigator.share({ files: [shareFile], title: 'MoTrack 集锦' });
    } catch (e) {
      if (e && e.name !== 'AbortError') toast('分享失败，可以点“下载”保存', true);
    }
  }

  /* ---------- phone access (desktop only) ---------- */
  function phoneView(info) {
    $('#phoneErr').classList.add('hidden');
    $('#phoneWait').classList.add('hidden');
    const on = !!(info && info.url);
    $('#phoneOff').classList.toggle('hidden', on);
    $('#phoneOn').classList.toggle('hidden', !on);
    if (on) {
      $('#phoneQr').src = info.qr; $('#phoneUrl').textContent = info.url; $('#phoneUrl').href = info.url;
      $('#phoneCode').textContent = info.code;
    }
    if (info && info.error && !on) { $('#phoneErr').textContent = info.error; $('#phoneErr').classList.remove('hidden'); }
    if (info && !info.available) { $('#phoneStart').disabled = true; }
  }
  async function openPhone() {
    $('#phoneDialog').classList.remove('hidden');
    try { phoneView(await api('/api/v1/remote')); } catch (e) { phoneView({ error: e.message }); }
  }
  async function startPhone() {
    $('#phoneOff').classList.add('hidden'); $('#phoneWait').classList.remove('hidden');
    try {
      let info = await api('/api/v1/remote/start', {});
      for (let i = 0; i < 40 && info.running && !info.url; i++) {  // cloudflared needs a few seconds for its URL
        await new Promise((r) => setTimeout(r, 700));
        info = await api('/api/v1/remote');
      }
      if (!info.url && !info.error) info.error = '开启超时，请再试一次';
      phoneView(info);
    } catch (e) { phoneView({ error: e.message }); }
  }
  async function resetPhone() {
    if (!confirm('重置后旧二维码立即失效，已登录的手机都需要重新扫码。确定吗？')) return;
    try { phoneView(await api('/api/v1/remote/reset', {})); toast('已换成新的二维码'); } catch (e) { toast(e.message, true); }
  }
  async function stopPhone() {
    try { phoneView(await api('/api/v1/remote/stop', {})); toast('已关闭手机访问'); } catch (e) { toast(e.message, true); }
  }
  async function checkPhone() {
    // The panel exists only for this computer's own browser.
    try { await api('/api/v1/remote'); $('#phoneBtn').classList.remove('hidden'); } catch (e) { /* phone or old backend */ }
  }

  /* ---------- install to home screen ---------- */
  // Only Android Chrome/Edge fire beforeinstallprompt.  Everywhere else
  // (iPhone, WeChat, phone-maker browsers) the button opens step-by-step
  // instructions for the browser actually in use.
  let installEvent = null;
  const standalone = () => window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  const isPhone = () => window.matchMedia('(pointer: coarse)').matches && Math.min(screen.width, screen.height) < 820;
  function browserInfo() {
    const ua = navigator.userAgent;
    const ios = /iP(hone|ad|od)/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    const name = /MicroMessenger/i.test(ua) ? 'wechat' : /\bQQ\//.test(ua) ? 'qq' : /AlipayClient/i.test(ua) ? 'alipay'
      : /Weibo/i.test(ua) ? 'weibo' : /DingTalk/i.test(ua) ? 'dingtalk' : /Lark|Feishu/i.test(ua) ? 'feishu'
      : /MiuiBrowser|XiaoMi\//i.test(ua) ? 'mi' : /HuaweiBrowser|HONORBrowser/i.test(ua) ? 'huawei'
      : /Quark/i.test(ua) ? 'quark' : /UCBrowser/i.test(ua) ? 'uc' : /MQQBrowser/i.test(ua) ? 'qqbrowser'
      : /HeyTapBrowser|OppoBrowser/i.test(ua) ? 'oppo' : /VivoBrowser/i.test(ua) ? 'vivo' : /SamsungBrowser/i.test(ua) ? 'samsung'
      : /EdgiOS|EdgA/i.test(ua) ? 'edge' : /CriOS|Chrome\//i.test(ua) ? 'chrome' : /FxiOS|Firefox/i.test(ua) ? 'firefox'
      : ios ? 'safari' : 'other';
    return { ios, name, inApp: ['wechat', 'qq', 'alipay', 'weibo', 'dingtalk', 'feishu'].includes(name) };
  }
  const APP_NAME = { wechat: '微信', qq: 'QQ', alipay: '支付宝', weibo: '微博', dingtalk: '钉钉', feishu: '飞书' };
  function installSteps() {
    const b = browserInfo();
    if (b.inApp) {
      return { title: APP_NAME[b.name] + '里不能安装，先换到浏览器', copy: true, steps: [
        '点右上角的 <b>···</b>',
        b.ios ? '选 <b>“在 Safari 中打开”</b>' : '选 <b>“在浏览器打开”</b>',
        '打开后，再点页面右上角的 <b>📲 安装</b>，按提示操作'] };
    }
    if (b.ios) {
      if (['safari', 'chrome', 'edge', 'firefox'].includes(b.name)) {
        return { title: '添加到主屏幕', steps: [
          '点地址栏旁边的 <b>分享按钮</b>（方框加向上箭头 ⬆️；新版 iOS 可能要先点 <b>···</b>）',
          '往下滑，选 <b>“添加到主屏幕”</b>',
          '点右上角 <b>“添加”</b>，主屏幕上就有 MoTrack 图标了'],
          note: b.name === 'safari' ? '' : '没有“添加到主屏幕”的话，用 Safari 打开这个网址再试。' };
      }
      return { title: '用 Safari 打开才能添加', copy: true, steps: ['复制网址', '打开 <b>Safari</b>，粘贴网址打开', '点 <b>分享 ⬆️</b> → <b>“添加到主屏幕”</b>'] };
    }
    const menu = { mi: '<b>☰</b>（底部菜单）→ <b>“添加到桌面”</b>', huawei: '<b>⋮</b> 或底部 <b>☰</b> → <b>“添加至桌面”</b>',
      quark: '底部 <b>☰</b> → <b>“添加到桌面”</b>', uc: '底部 <b>☰</b> → <b>“添加到桌面”</b>', qqbrowser: '底部 <b>☰</b> → <b>“添加到桌面”</b>',
      oppo: '<b>⋮</b> → <b>“添加到桌面”</b>', vivo: '<b>☰</b> → <b>“添加到桌面”</b>', samsung: '<b>☰</b> → <b>“添加页面到”</b> → <b>“主屏幕”</b>',
      chrome: '右上角 <b>⋮</b> → <b>“添加到主屏幕”</b> 或 <b>“安装应用”</b>', edge: '底部 <b>···</b> → <b>“添加到手机”</b>',
      firefox: '<b>⋮</b> → <b>“安装”</b> 或 <b>“添加到主屏幕”</b>' }[b.name] || '浏览器菜单（<b>⋮</b> 或 <b>☰</b>）→ <b>“添加到桌面 / 主屏幕”</b>';
    return { title: '添加到桌面', steps: ['点 ' + menu, '确认添加，桌面上就有 MoTrack 图标了'],
      note: '小米、华为、OPPO、vivo 手机如果没反应：到系统设置 → 应用 → 这个浏览器 → 权限，打开 <b>“桌面快捷方式”</b>。还不行就用 Chrome 打开。' };
  }
  function openInstall() {
    const s = installSteps();
    $('#installTitle').textContent = s.title;
    $('#installSteps').innerHTML = s.steps.map((t) => '<li>' + t + '</li>').join('');
    $('#installNote').innerHTML = s.note || '';
    $('#installNote').classList.toggle('hidden', !s.note);
    $('#installCopy').classList.toggle('hidden', !s.copy);
    $('#installDialog').classList.remove('hidden');
  }
  async function install() {
    if (installEvent) {  // Android Chrome / Edge: the real install prompt
      const event = installEvent; installEvent = null;
      try {
        await event.prompt();
        if ((await event.userChoice).outcome === 'accepted') return;
      } catch (e) { /* prompt refused or dismissed: show the manual steps */ }
    }
    openInstall();
  }
  async function copyLink() {
    const url = location.origin + '/app/index.html';
    try { await navigator.clipboard.writeText(url); toast('网址已复制'); }
    catch (e) { prompt('长按复制这个网址：', url); }
  }
  window.addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); installEvent = e; });
  window.addEventListener('appinstalled', () => { $('#installBtn').classList.add('hidden'); $('#installTip').classList.add('hidden'); toast('已添加到主屏幕 🎉'); });
  function installUI() {
    if (standalone() || !isPhone()) return;
    $('#installBtn').classList.remove('hidden');
    let seen = false;
    try { seen = localStorage.getItem('motrack_install_tip') === '1'; } catch (e) { /* private mode */ }
    if (!seen) {
      const b = browserInfo();
      $('#installTipText').innerHTML = b.inApp ? '在' + APP_NAME[b.name] + '里打开的？点右上角 <b>···</b> 换到浏览器，就能把 MoTrack 放到桌面。'
        : '把 MoTrack 放到桌面，像 App 一样打开。';
      $('#installTip').classList.remove('hidden');
    }
  }
  if ('serviceWorker' in navigator && window.isSecureContext) {
    navigator.serviceWorker.register('/app/sw.js', { scope: '/app/' }).catch(() => {});
  }

  /* ---------- bindings ---------- */
  $('#logo').src = $('#favicon').href;
  $('#videos').addEventListener('click', (e) => {
    const del = e.target.closest('[data-del]');
    if (del) { e.stopPropagation(); deleteVideo(del.dataset.del); return; }
    if (e.target.closest('#uploadCard')) { if (!state.busy) $('#videoFile').click(); return; }
    const b = e.target.closest('.vcard[data-id]'); if (b) selectVideo(b.dataset.id);
  });
  $('#videoFile').addEventListener('change', (e) => uploadVideo(e.target.files[0]));
  $('#share').addEventListener('click', share);
  $('#phoneBtn').addEventListener('click', openPhone);
  $('#phoneStart').addEventListener('click', startPhone);
  $('#phoneStop').addEventListener('click', stopPhone);
  $('#phoneReset').addEventListener('click', resetPhone);
  $('#phoneClose').addEventListener('click', () => $('#phoneDialog').classList.add('hidden'));
  $('#phoneDialog').addEventListener('click', (e) => { if (e.target === e.currentTarget) $('#phoneDialog').classList.add('hidden'); });
  $('#installBtn').addEventListener('click', install);
  $('#installTipGo').addEventListener('click', install);
  $('#installTipClose').addEventListener('click', () => {
    $('#installTip').classList.add('hidden');
    try { localStorage.setItem('motrack_install_tip', '1'); } catch (e) { /* private mode */ }
  });
  $('#installCopy').addEventListener('click', copyLink);
  $('#installClose').addEventListener('click', () => $('#installDialog').classList.add('hidden'));
  $('#installDialog').addEventListener('click', (e) => { if (e.target === e.currentTarget) $('#installDialog').classList.add('hidden'); });
  $$('.mode').forEach((b) => b.addEventListener('click', () => setMode(b.dataset.mode)));
  $('#presets').addEventListener('click', (e) => { const b = e.target.closest('.preset'); if (b) { stopPreview(); applyPreset(b.dataset.id); } });
  $('#durations').addEventListener('click', (e) => {
    const b = e.target.closest('.chip'); if (!b) return;
    state.duration = Number(b.dataset.d); renderDurations();
  });
  ['aspect', 'focus'].forEach((id) => $('#' + id).addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (b) setSeg(id, b.dataset.value);
  }));
  ['pace', 'transition', 'look'].forEach((id) => $('#' + id).addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (b) { setSeg(id, b.dataset.value); matchPreset(); }
  }));
  ['#zoom', '#slowmo'].forEach((s) => $(s).addEventListener('change', matchPreset));
  $('#music').addEventListener('click', (e) => {
    const b = e.target.closest('.chip'); if (!b) return;
    stopPreview(); state.music = b.dataset.id; renderMusic(); matchPreset();
  });
  $('#musicPreview').addEventListener('click', previewMusic);
  $('#musicAudio').addEventListener('ended', stopPreview);
  $('#musicFile').addEventListener('change', (e) => uploadMusic(e.target.files[0]));
  $('#title').addEventListener('input', () => { state.titleOff = false; });
  $$('#viewToggle button').forEach((b) => b.addEventListener('click', () => showView(b.dataset.view)));
  $('#moments').addEventListener('click', (e) => {
    const b = e.target.closest('.moment'); if (!b) return;
    if (!state.output) $('#viewToggle').classList.remove('hidden');
    showView('source'); $('#empty').classList.add('hidden');
    const v = $('#source'); v.currentTime = Math.max(0, Number(b.dataset.t) - 1); v.play().catch(() => {});
    $('.player').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  });
  $('#filmTrack').addEventListener('click', (e) => {
    const b = e.target.closest('.seg-item'); if (!b) return;
    showView('highlight');
    const v = $('#highlight'); v.currentTime = Number(b.dataset.out) + 0.05; v.play().catch(() => {});
  });
  $('#log').addEventListener('click', (e) => {
    if (!e.target.closest('[data-play]')) return;
    showView('highlight'); const v = $('#highlight'); v.currentTime = 0; v.play().catch(() => {});
    $('.player').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  });
  $$('.tabs button').forEach((b) => b.addEventListener('click', () => showPane(b.dataset.pane)));
  $('#askAi').addEventListener('click', () => { showPane('chat'); $('#msg').focus(); });
  $('#go').addEventListener('click', generate);
  $('#send').addEventListener('click', () => send());
  $('#suggest').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) send(b.textContent); });
  $('#newChat').addEventListener('click', () => { if (!state.busy) resetChat(); });
  $('#msg').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); send(); }
  });
  $('#msg').addEventListener('input', () => { const t = $('#msg'); t.style.height = 'auto'; t.style.height = Math.min(110, t.scrollHeight) + 'px'; });
  $('#vipPill').addEventListener('click', openVip);
  $('#vipClose').addEventListener('click', closeVip);
  $('#vipDialog').addEventListener('click', (e) => { if (e.target === e.currentTarget) closeVip(); });
  $('#vipActivate').addEventListener('click', activate);
  $('#vipCode').addEventListener('keydown', (e) => { if (e.key === 'Enter') activate(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeVip(); $('#phoneDialog').classList.add('hidden'); $('#installDialog').classList.add('hidden'); } });

  (async function init() {
    applyPreset('hype'); renderMode(); resetChat(); renderSteps();
    await Promise.all([checkBackend(), checkVip(), loadMusic()]);
    applyPreset('hype'); renderMode(); resetChat(); installUI(); checkPhone();
    await loadVideos();
  })();
})();
