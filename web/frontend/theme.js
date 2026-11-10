/* Theme: auto (follow the system) / light / dark, remembered per browser.
   Loaded in <head> without defer so the right colors apply before first paint. */
(() => {
  const KEY = 'motrack_theme';
  const ORDER = ['auto', 'light', 'dark'];
  const ICON = { auto: '🌓', light: '☀️', dark: '🌙' };
  const LABEL = { auto: '跟随系统', light: '浅色', dark: '深色' };
  const root = document.documentElement;
  const media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: light)') : null;
  function saved() { try { return localStorage.getItem(KEY) || 'auto'; } catch (e) { return 'auto'; } }
  function effective(mode) { return mode === 'auto' ? (media && media.matches ? 'light' : 'dark') : mode; }
  function apply(mode) {
    if (mode === 'auto') root.removeAttribute('data-theme'); else root.setAttribute('data-theme', mode);
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', effective(mode) === 'light' ? '#f3f5fa' : '#070a12');
    document.querySelectorAll('[data-theme-toggle]').forEach((b) => {
      b.textContent = ICON[mode]; b.title = '主题：' + LABEL[mode] + '（点一下切换）'; b.setAttribute('aria-label', b.title);
    });
  }
  apply(saved());
  if (media && media.addEventListener) media.addEventListener('change', () => { if (saved() === 'auto') apply('auto'); });
  window.MoTheme = {
    next() {
      const mode = ORDER[(ORDER.indexOf(saved()) + 1) % ORDER.length];
      try { localStorage.setItem(KEY, mode); } catch (e) { /* private mode: this page only */ }
      apply(mode);
      return LABEL[mode];
    },
    label() { return LABEL[saved()]; }
  };
  document.addEventListener('DOMContentLoaded', () => {
    apply(saved());
    document.querySelectorAll('[data-theme-toggle]').forEach((b) => b.addEventListener('click', () => {
      const label = window.MoTheme.next();
      const t = document.getElementById('toast');
      if (t) { t.textContent = '主题：' + label; t.classList.add('show'); setTimeout(() => t.classList.remove('show'), 1600); }
    }));
  });
})();
