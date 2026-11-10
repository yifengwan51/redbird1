(() => {
  const $ = (s) => document.querySelector(s);
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const when = (ts) => {
    if (!ts) return '';
    const d = new Date(ts * 1000), now = Date.now(), m = Math.round((now - d) / 60000);
    return m < 1 ? '刚刚' : m < 60 ? m + ' 分钟前' : m < 1440 ? Math.round(m / 60) + ' 小时前' : (d.getMonth() + 1) + '月' + d.getDate() + '日';
  };
  let tab = 'pending', data = null, siteUrl = '', lastPending = null;
  const canNotify = 'Notification' in window && window.isSecureContext;
  function notifyUI() {
    const row = $('#notifyRow');
    if (!canNotify) { row.textContent = '提示：这个浏览器不支持桌面提醒，有新申请时标签页标题会显示数字。'; return; }
    if (Notification.permission === 'granted') row.textContent = '🔔 已开启：有新申请时会弹出提醒（页面需要开着）。';
    else if (Notification.permission === 'denied') row.textContent = '提醒被浏览器禁止了，可以在浏览器设置里允许通知。';
  }
  let toastTimer = 0;
  function toast(text, bad) {
    const t = $('#toast'); t.textContent = text; t.classList.toggle('bad', !!bad); t.classList.add('show');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove('show'), 2600);
  }
  async function api(path, body) {
    const res = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
    if (res.status === 401 || res.status === 403 && path.startsWith('/api/v1/admin')) { location.href = '/app/login.html?admin=1'; throw new Error('请先登录'); }
    const out = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof out.detail === 'string' ? out.detail : '操作失败');
    return out;
  }
  async function loadSite() {
    try {
      const s = await api('/api/v1/admin/site');
      siteUrl = s.url || '';
      $('#siteUrl').innerHTML = siteUrl ? '<a href="' + esc(siteUrl) + '" target="_blank" rel="noopener">' + esc(siteUrl) + '</a>'
        : (s.error ? esc(s.error) : '公网访问没有开启，现在只有这台电脑能打开。');
      if (s.qr) { $('#siteQr').src = s.qr; $('#siteQr').classList.remove('hidden'); } else $('#siteQr').classList.add('hidden');
      $('#startTunnel').classList.toggle('hidden', !!s.running);
      $('#phoneCard').classList.toggle('hidden', !s.admin_qr);
      if (s.admin_qr) { $('#adminQr').src = s.admin_qr; $('#adminUrl').textContent = s.admin_url; }
      $('#devices').textContent = s.devices ? '现在有 ' + s.devices + ' 台手机登录着管理员身份。' : '还没有手机登录。';
      if (!s.running) $('#siteNote').textContent = '电脑重启或断网后，公网地址会变，到时回到这台电脑重新扫码即可。';
      $('#copyUrl').classList.toggle('hidden', !siteUrl);
    } catch (e) { $('#siteUrl').textContent = e.message; }
  }
  async function load() {
    try { data = await api('/api/v1/admin/visitors'); } catch (e) { $('#list').innerHTML = '<div class="none">' + esc(e.message) + '</div>'; return; }
    const st = data.settings;
    if (document.activeElement.tagName !== 'INPUT') {
      $('#public').checked = !!st.public; $('#free').value = st.free_ai_uses; $('#ipFree').value = st.ip_daily_free; $('#uploads').value = st.visitor_uploads;
    }
    const n = data.counts.pending || 0;
    if (lastPending !== null && n > lastPending && canNotify && Notification.permission === 'granted') {
      const who = data.visitors.find((v) => v.status === 'pending');
      try { new Notification('MoTrack：有新的使用申请', { body: (who && who.name ? who.name + ' ' : '') + '等你审核', icon: '/app/icons/icon-192.png' }); } catch (e) { /* ignore */ }
    }
    lastPending = n;
    $('#nPending').textContent = n; $('#nPending').classList.toggle('hidden', !n);
    document.title = (n ? '(' + n + ') ' : '') + 'MoTrack 管理';
    render();
  }
  function render() {
    const rows = data.visitors.filter((v) => v.status === tab);
    const free = data.settings.free_ai_uses;
    if (!rows.length) {
      $('#list').innerHTML = '<div class="none">' + { pending: '没有待审核的申请', approved: '还没有通过的访客', rejected: '没有被拒绝的访客', free: '还没有访客用过 AI 功能' }[tab] + '</div>';
      return;
    }
    $('#list').innerHTML = rows.map((v) => {
      const acts = {
        pending: '<button class="btn-s ok" data-a="approve">通过</button><button class="btn-s no" data-a="reject">拒绝</button>',
        approved: '<button class="btn-s no" data-a="revoke">取消资格</button>',
        rejected: '<button class="btn-s ok" data-a="approve">改为通过</button><button class="btn-s" data-a="reset">重新给免费次数</button>',
        free: '<button class="btn-s ok" data-a="approve">直接通过</button><button class="btn-s" data-a="reset">重置次数</button>'
      }[tab];
      const meta = [v.note ? '备注：' + v.note : '', 'AI 已用 ' + v.uses + (tab === 'free' ? ' / ' + free : '') + ' 次',
        v.uploads ? '上传 ' + v.uploads + ' 个视频' : '', v.applied ? '申请于 ' + when(v.applied) : v.last_used ? '最近使用 ' + when(v.last_used) : '',
        v.ip ? 'IP ' + v.ip : ''].filter(Boolean).join(' · ');
      return '<div class="item" data-id="' + esc(v.id) + '"><div class="who"><b>' + esc(v.name || '（未填写姓名）') + '</b><small>' + esc(meta) + '</small></div>' +
        '<div class="acts">' + acts + '</div></div>';
    }).join('');
  }
  $('#list').addEventListener('click', async (e) => {
    const b = e.target.closest('[data-a]'); if (!b) return;
    const id = b.closest('.item').dataset.id;
    b.disabled = true;
    try {
      await api('/api/v1/admin/visitors/' + encodeURIComponent(id), { action: b.dataset.a });
      toast({ approve: '已通过', reject: '已拒绝', revoke: '已取消资格', reset: '已重置免费次数' }[b.dataset.a]);
      await load();
    } catch (err) { toast(err.message, true); b.disabled = false; }
  });
  $('#tabs').addEventListener('click', (e) => {
    const b = e.target.closest('[data-s]'); if (!b) return;
    tab = b.dataset.s;
    document.querySelectorAll('#tabs button').forEach((x) => x.classList.toggle('active', x === b));
    if (data) render();
  });
  $('#save').addEventListener('click', async () => {
    try {
      await api('/api/v1/admin/settings', { public: $('#public').checked, free_ai_uses: Number($('#free').value),
        ip_daily_free: Number($('#ipFree').value), visitor_uploads: Number($('#uploads').value) });
      toast('已保存'); load();
    } catch (e) { toast(e.message, true); }
  });
  $('#copyUrl').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(siteUrl); toast('网址已复制'); }
    catch (e) { toast('复制失败，请长按网址手动复制', true); }
  });
  $('#startTunnel').addEventListener('click', async () => {
    $('#startTunnel').disabled = true; $('#siteUrl').textContent = '正在开启，大约 5–10 秒…';
    try { await api('/api/v1/remote/start', {}); } catch (e) { toast(e.message, true); }
    setTimeout(() => { loadSite(); $('#startTunnel').disabled = false; }, 6000);
  });
  $('#signoutAll').addEventListener('click', async () => {
    if (!confirm('让所有已登录的手机退出？二维码也会换一个新的，旧码失效。访问口令不变。')) return;
    try { await api('/api/v1/admin/signout-all', {}); toast('所有手机已退出，二维码已换新'); loadSite(); }
    catch (e) { toast(e.message, true); }
  });
  $('#notify').addEventListener('click', async () => { try { await Notification.requestPermission(); } catch (e) { /* ignore */ } notifyUI(); });
  notifyUI();
  load(); loadSite();
  setInterval(load, 15000);
})();
