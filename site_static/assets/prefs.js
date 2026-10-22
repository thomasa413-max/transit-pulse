// Applies saved display settings before the page is painted (no flash). Kept tiny on purpose.
(function (r) {
  try {
    var s = localStorage, t = s.getItem('tp_theme'), k = parseFloat(s.getItem('tp_scale'));
    if (t === 'light' || t === 'dark') r.setAttribute('data-theme', t);
    if (k >= 0.85 && k <= 1.8) r.style.setProperty('--scale', k);
    if (s.getItem('tp_font') === '1') r.classList.add('lisible');
  } catch (e) {}
})(document.documentElement);
