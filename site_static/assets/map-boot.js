// Starts the 3D map (engine ~1 MB, then swisstopo tiles) once the page itself is ready.
// Devices without a graphics chip (software rendering) or with data saving turned on see a
// still preview and a button instead, so the page stays fast and light for them.
(function () {
  var box = document.getElementById('carte');
  if (!box) return;
  var status = document.getElementById('carte-etat');
  var T = JSON.parse(document.getElementById('carte-i18n').textContent);
  var facade = document.getElementById('carte-apercu');
  var gl = null;
  try { gl = document.createElement('canvas').getContext('webgl2'); } catch (e) { gl = null; }
  if (!gl) { status.textContent = T.map_nowebgl; return; }
  var renderer = '';
  try {
    var dbg = gl.getExtension('WEBGL_debug_renderer_info');
    renderer = String(gl.getParameter(dbg ? dbg.UNMASKED_RENDERER_WEBGL : gl.RENDERER) || '');
  } catch (e) { renderer = ''; }
  var software = /swiftshader|llvmpipe|softpipe|software|basic render/i.test(renderer);
  var saveData = !!(navigator.connection && navigator.connection.saveData);
  var started = false;
  function start() {
    if (started) return;
    started = true;
    if (facade) facade.hidden = true;
    status.hidden = false;
    var s = document.createElement('script');
    s.type = 'module';
    s.src = box.getAttribute('data-module');
    s.onerror = function () { status.textContent = T.map_nowebgl; };
    document.head.appendChild(s);
  }
  if (software || saveData) {
    status.hidden = true;
    if (facade) {
      facade.hidden = false;
      facade.querySelector('button').addEventListener('click', function () { start(); box.focus(); });
    }
    return;
  }
  function idle() { (window.requestIdleCallback || function (f) { setTimeout(f, 200); })(start, { timeout: 2000 }); }
  if (document.readyState === 'complete') idle(); else window.addEventListener('load', idle);
})();
