// Loads the 3D map engine (~1 MB) only once the page itself is ready, so the text,
// the stop table and Core Web Vitals do not wait for it.
(function () {
  var box = document.getElementById('carte');
  if (!box) return;
  var status = document.getElementById('carte-etat');
  var T = JSON.parse(document.getElementById('carte-i18n').textContent);
  function webgl() {
    try { var c = document.createElement('canvas'); return !!c.getContext('webgl2'); } catch (e) { return false; }
  }
  if (!webgl()) { status.textContent = T.map_nowebgl; return; }
  function start() {
    var s = document.createElement('script');
    s.type = 'module';
    s.src = box.getAttribute('data-module');
    s.onerror = function () { status.textContent = T.map_nowebgl; };
    document.head.appendChild(s);
  }
  function idle() { (window.requestIdleCallback || function (f) { setTimeout(f, 200); })(start, { timeout: 2000 }); }
  if (document.readyState === 'complete') idle(); else window.addEventListener('load', idle);
})();
