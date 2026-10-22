// Transit Pulse: language menu, display settings, anonymous visit count and Core Web Vitals.
(function () {
  var root = document.documentElement;
  var lang = (root.lang || 'fr').slice(0, 2);
  var store = {
    get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  };
  var $ = function (id) { return document.getElementById(id); };

  // ---- Disclosure buttons (language menu, settings panel)
  function disclosure(btn, panel, focusFirst) {
    if (!btn || !panel) return;
    function close() { panel.hidden = true; btn.setAttribute('aria-expanded', 'false'); }
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      var open = panel.hidden;
      panel.hidden = !open; btn.setAttribute('aria-expanded', String(open));
      if (open && focusFirst) { var a = panel.querySelector('a, button'); if (a) a.focus(); }
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !panel.hidden) { close(); btn.focus(); } });
    return close;
  }
  var langMenu = $('lang-menu');
  var closeLang = disclosure($('btn-lang'), langMenu, true);
  document.addEventListener('click', function (e) { if (langMenu && !langMenu.hidden && !langMenu.contains(e.target)) closeLang(); });
  disclosure($('btn-reglages'), $('reglages'), false);
  // Remember the chosen language (read by the server when someone opens the site's root address).
  document.querySelectorAll('.lang-menu a[lang]').forEach(function (a) {
    a.addEventListener('click', function () {
      document.cookie = 'lang=' + a.getAttribute('lang') + '; Path=/; Max-Age=31536000; SameSite=Lax; Secure';
    });
  });

  // ---- Display settings
  var scale = parseFloat(store.get('tp_scale')) || 1, out = $('taille-val');
  function applyScale() {
    scale = Math.min(1.8, Math.max(0.85, Math.round(scale * 100) / 100));
    root.style.setProperty('--scale', scale);
    if (out) out.textContent = Math.round(scale * 100) + (lang === 'en' || lang === 'it' ? '%' : ' %');
    store.set('tp_scale', scale);
  }
  if ($('plus')) {
    $('plus').addEventListener('click', function () { scale += 0.15; applyScale(); });
    $('moins').addEventListener('click', function () { scale -= 0.15; applyScale(); });
    applyScale();
  }
  var fs = $('pol-standard'), fl = $('pol-lisible');
  function applyFont(on) {
    root.classList.toggle('lisible', on);
    if (fs) { fs.setAttribute('aria-pressed', String(!on)); fl.setAttribute('aria-pressed', String(on)); }
    store.set('tp_font', on ? '1' : '0');
  }
  if (fs) {
    fs.addEventListener('click', function () { applyFont(false); });
    fl.addEventListener('click', function () { applyFont(true); });
    applyFont(store.get('tp_font') === '1');
  }
  var themeBtns = document.querySelectorAll('[data-theme-set]');
  function applyTheme(th) {
    if (th === 'light' || th === 'dark') root.setAttribute('data-theme', th); else root.removeAttribute('data-theme');
    themeBtns.forEach(function (b) { b.setAttribute('aria-pressed', String(b.getAttribute('data-theme-set') === th)); });
    store.set('tp_theme', th);
  }
  themeBtns.forEach(function (b) { b.addEventListener('click', function () { applyTheme(b.getAttribute('data-theme-set')); }); });
  applyTheme(store.get('tp_theme') || 'system');

  // ---- Anonymous statistics (daily totals only; nothing sent if Do Not Track / GPC is on)
  var noTrack = navigator.doNotTrack === '1' || window.doNotTrack === '1' || navigator.globalPrivacyControl === true;
  var publicPage = /^\/(fr|de|it|en)\//.test(location.pathname) && !/\/404\.html$/.test(location.pathname);
  if (!window.fetch || noTrack || !publicPage) return;
  function post(path, data) {
    var body = JSON.stringify(data);
    if (navigator.sendBeacon && path === '/api/vitals') {
      navigator.sendBeacon(path, new Blob([body], { type: 'application/json' }));
    } else {
      fetch(path, { method: 'POST', credentials: 'same-origin', keepalive: true,
        headers: { 'Content-Type': 'application/json' }, body: body }).catch(function () {});
    }
  }
  post('/api/visit', { path: location.pathname, ref: document.referrer || '' });

  // ---- Core Web Vitals measured on real visits (LCP, CLS, INP, FCP, TTFB)
  if (!('PerformanceObserver' in window)) return;
  var vitals = {}, sent = false;
  function observe(type, fn) {
    try { new PerformanceObserver(function (l) { l.getEntries().forEach(fn); }).observe({ type: type, buffered: true }); } catch (e) {}
  }
  observe('largest-contentful-paint', function (e) { vitals.LCP = e.startTime; });
  observe('paint', function (e) { if (e.name === 'first-contentful-paint') vitals.FCP = e.startTime; });
  var cls = 0, sessionValue = 0, sessionEntries = [];
  observe('layout-shift', function (e) {
    if (e.hadRecentInput) return;
    var first = sessionEntries[0], last = sessionEntries[sessionEntries.length - 1];
    if (sessionValue && e.startTime - last.startTime < 1000 && e.startTime - first.startTime < 5000) {
      sessionValue += e.value; sessionEntries.push(e);
    } else { sessionValue = e.value; sessionEntries = [e]; }
    if (sessionValue > cls) { cls = sessionValue; vitals.CLS = cls; }
  });
  var inp = 0;
  try {
    new PerformanceObserver(function (l) {
      l.getEntries().forEach(function (e) { if (e.interactionId && e.duration > inp) { inp = e.duration; vitals.INP = inp; } });
    }).observe({ type: 'event', buffered: true, durationThreshold: 40 });
  } catch (e) {}
  try {
    var nav = performance.getEntriesByType('navigation')[0];
    if (nav) vitals.TTFB = nav.responseStart;
  } catch (e) {}
  function flush() {
    if (sent) return; sent = true;
    var list = [];
    Object.keys(vitals).forEach(function (k) { list.push({ name: k, value: Math.round(k === 'CLS' ? vitals[k] * 1000 : vitals[k]) }); });
    if (list.length) post('/api/vitals', { path: location.pathname, metrics: list,
      device: /Mobi|Android|iPhone/i.test(navigator.userAgent) ? 'mobile' : 'desktop' });
  }
  document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'hidden') flush(); });
  window.addEventListener('pagehide', flush);
})();
