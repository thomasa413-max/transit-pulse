// Visit statistics: daily totals, countries, where visitors come from, pages, devices, languages.
TPAdmin.ready(function () {
  var A = TPAdmin, el = A.el, days = 30;
  var LANG = { fr: 'Français', de: 'Deutsch', it: 'Italiano', en: 'English' };
  function load() {
    A.api('/api/admin/stats?days=' + days).then(function (d) {
      var choice = el('div', { class: 'adm-filters', role: 'group', 'aria-label': 'Période' });
      [7, 30, 90, 365].forEach(function (n) {
        var b = el('button', { type: 'button', class: 'tool', 'aria-pressed': String(n === days) }, n + ' jours');
        b.addEventListener('click', function () { days = n; load(); }); choice.appendChild(b);
      });
      var byDay = {};
      d.daily.forEach(function (r) { (byDay[r.day] = byDay[r.day] || {})[r.kind] = r.n; });
      var sum = function (k) { return Object.keys(byDay).reduce(function (s, day) { return s + (byDay[day][k] || 0); }, 0); };
      var tiles = el('div', { class: 'tiles' });
      [['Visiteurs', sum('visitors')], ['Nouveaux visiteurs', sum('new')], ['Pages vues', sum('views')], ['Depuis l’ouverture', d.allTime]]
        .forEach(function (x) {
          var t = el('div', { class: 'tile' }); t.appendChild(el('p', { class: 'tile-label' }, x[0]));
          t.appendChild(el('p', { class: 'tile-value' }, A.nf.format(x[1] || 0))); tiles.appendChild(t);
        });
      var dayRows = Object.keys(byDay).sort().reverse().map(function (day) { return { key: day, n: byDay[day].visitors || 0 }; });
      A.mount([choice, tiles,
        A.section('Visiteurs par jour', A.bars(dayRows)),
        A.section('Pays', A.bars(d.top.country, A.country)),
        A.section('Provenance (site d’origine)', A.bars(d.top.referrer, function (k) { return k === 'direct' ? 'Accès direct ou favori' : k; })),
        A.section('Pages les plus vues', A.bars(d.top.page)),
        A.section('Appareils', A.bars(d.top.device)),
        A.section('Langues', A.bars(d.top.lang, function (k) { return LANG[k] || k; })),
        el('p', { class: 'method' }, 'Totaux par jour uniquement, sans adresse IP ni identifiant. Robots et navigateurs « Do Not Track » / GPC exclus. Historique effacé après 400 jours.')]);
    }).catch(function () { A.mount([el('p', { class: 'notice' }, 'Données indisponibles.')]); });
  }
  load();
});
