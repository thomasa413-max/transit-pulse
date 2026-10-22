// Administration core: login with an HttpOnly session cookie (the password is never stored in the browser),
// shared menu, API helper. Each page registers its loader with TPAdmin.ready(fn).
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var hooks = [], connected = false;
  function show(on) {
    connected = on;
    $('connexion').hidden = on; $('app').hidden = !on;
    $('menu-admin').hidden = !on; $('deconnexion').hidden = !on;
  }
  function api(path, opts) {
    opts = opts || {};
    return fetch(path, { method: opts.method || 'GET', credentials: 'same-origin',
      headers: opts.body ? { 'Content-Type': 'application/json' } : {}, body: opts.body ? JSON.stringify(opts.body) : undefined })
      .then(function (r) {
        if (r.status === 401) { show(false); throw new Error('auth'); }
        return r.json().then(function (d) { if (!r.ok) { var e = new Error(d.error || 'server'); e.status = r.status; throw e; } return d; });
      });
  }
  function badge() {
    api('/api/admin/summary').then(function (d) {
      var b = $('nb-attente'); if (!b) return;
      b.textContent = d.pending; b.hidden = !d.pending; b.setAttribute('aria-label', d.pending + ' en attente');
    }).catch(function () {});
  }
  function start() { show(true); hooks.forEach(function (fn) { try { fn(); } catch (e) { console.error(e); } }); badge(); }

  window.TPAdmin = {
    api: api,
    ready: function (fn) { hooks.push(fn); if (connected) fn(); },
    refreshBadge: badge,
    el: function (tag, attrs, text) {
      var e = document.createElement(tag);
      if (attrs) for (var k in attrs) { if (k === 'class') e.className = attrs[k]; else e.setAttribute(k, attrs[k]); }
      if (text !== undefined && text !== null) e.textContent = text;
      return e;
    },
    nf: new Intl.NumberFormat('fr-CH'),
    country: function (code) {
      if (!code || code === '??') return 'Inconnu';
      try { return new Intl.DisplayNames(['fr'], { type: 'region' }).of(code) + ' (' + code + ')'; } catch (e) { return code; }
    },
    bars: function (rows, labelFn) {
      var box = TPAdmin.el('div', { class: 'bars' });
      var max = Math.max.apply(null, rows.map(function (r) { return r.n; }).concat([1]));
      rows.forEach(function (r) {
        var row = TPAdmin.el('div', { class: 'bar-row' });
        row.appendChild(TPAdmin.el('span', null, labelFn ? labelFn(r.key) : r.key));
        var track = TPAdmin.el('span', { class: 'track', 'aria-hidden': 'true' }), fill = TPAdmin.el('span', { class: 'fill' });
        fill.style.width = Math.round(100 * r.n / max) + '%'; track.appendChild(fill); row.appendChild(track);
        row.appendChild(TPAdmin.el('span', { class: 'num' }, TPAdmin.nf.format(r.n)));
        box.appendChild(row);
      });
      if (!rows.length) box.appendChild(TPAdmin.el('p', { class: 'muted' }, 'Aucune donnée pour cette période.'));
      return box;
    },
    section: function (title, child) {
      var s = TPAdmin.el('section', { class: 'block' }); s.appendChild(TPAdmin.el('h2', null, title));
      if (child) s.appendChild(child); return s;
    },
    mount: function (nodes) {
      var c = $('contenu-admin'); c.textContent = '';
      nodes.forEach(function (n) { if (n) c.appendChild(n); });
    }
  };

  $('form-connexion').addEventListener('submit', function (e) {
    e.preventDefault();
    var err = $('erreur-connexion'); err.textContent = '';
    fetch('/api/admin/login', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: $('mdp').value }) })
      .then(function (r) {
        $('mdp').value = '';
        if (r.ok) return start();
        err.textContent = r.status === 429 ? 'Trop de tentatives. Réessayez dans 15 minutes.'
          : r.status === 503 ? 'Administration non configurée : secrets ADMIN_PASSWORD et SESSION_SECRET manquants dans Cloudflare.'
          : 'Mot de passe incorrect.';
        $('mdp').focus();
      }).catch(function () { err.textContent = 'Serveur injoignable.'; });
  });
  $('deconnexion').addEventListener('click', function () {
    fetch('/api/admin/logout', { method: 'POST', credentials: 'same-origin' }).then(function () { show(false); $('mdp').focus(); });
  });
  fetch('/api/admin/me', { credentials: 'same-origin' }).then(function (r) { if (r.ok) start(); else { show(false); $('mdp').focus(); } })
    .catch(function () { show(false); });
})();
