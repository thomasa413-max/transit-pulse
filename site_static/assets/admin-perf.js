// Performance: Core Web Vitals from real visits (p75, as Google evaluates them) and the latest Lighthouse run.
TPAdmin.ready(function () {
  var A = TPAdmin, el = A.el;
  var NAMES = { LCP: 'Largest Contentful Paint', INP: 'Interaction to Next Paint', CLS: 'Cumulative Layout Shift',
    FCP: 'First Contentful Paint', TTFB: 'Time to First Byte' };
  function fmt(metric, v) {
    if (v === null) return 'au-delà de l’échelle';
    if (metric === 'CLS') return (v / 1000).toFixed(2).replace('.', ',');
    return v >= 1000 ? (v / 1000).toFixed(1).replace('.', ',') + ' s' : v + ' ms';
  }
  function tone(m) { return m.p75 === null || m.p75 > m.threshold_poor ? 'bad' : m.p75 > m.threshold_good ? 'warn' : 'good'; }
  Promise.all([
    A.api('/api/admin/vitals?days=28'),
    fetch('/admin/lighthouse.json', { credentials: 'same-origin', cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; })
  ]).then(function (res) {
    var v = res[0].vitals, lh = res[1];
    var rows = el('div', { class: 'table-wrap' }), table = el('table'), head = el('tr');
    ['Mesure', 'Appareil', 'p75', 'Bonnes', 'Mauvaises', 'Visites', 'Seuil « bon »'].forEach(function (h) { head.appendChild(el('th', { scope: 'col' }, h)); });
    var thead = el('thead'); thead.appendChild(head); table.appendChild(thead);
    var tb = el('tbody'), keys = Object.keys(v);
    keys.forEach(function (k) {
      var m = v[k], tr = el('tr');
      tr.appendChild(el('td', null, m.metric + ' · ' + NAMES[m.metric]));
      tr.appendChild(el('td', null, m.device === 'mobile' ? 'Mobile' : 'Ordinateur'));
      var td = el('td', { class: 'num' }); td.appendChild(el('span', { class: 'score ' + tone(m) }, fmt(m.metric, m.p75))); tr.appendChild(td);
      tr.appendChild(el('td', { class: 'num' }, Math.round(m.good * 100) + ' %'));
      tr.appendChild(el('td', { class: 'num' }, Math.round(m.poor * 100) + ' %'));
      tr.appendChild(el('td', { class: 'num' }, A.nf.format(m.samples)));
      tr.appendChild(el('td', { class: 'num' }, fmt(m.metric, m.threshold_good)));
      tb.appendChild(tr);
    });
    table.appendChild(tb); rows.appendChild(table);
    var real = keys.length ? rows : el('p', { class: 'empty' }, 'Pas encore de mesure : les données arrivent avec les premières visites.');
    var lhBox = el('div');
    if (lh && lh.pages) {
      lhBox.appendChild(el('p', { class: 'muted' }, 'Mesure du ' + new Date(lh.at).toLocaleString('fr-CH', { timeZone: 'Europe/Zurich' }) + ', mobile simulé.'));
      var t2 = el('table'), h2 = el('tr');
      ['Page', 'Performance', 'Accessibilité', 'Bonnes pratiques', 'SEO', 'LCP', 'CLS', 'TBT'].forEach(function (h) { h2.appendChild(el('th', { scope: 'col' }, h)); });
      var th2 = el('thead'); th2.appendChild(h2); t2.appendChild(th2);
      var b2 = el('tbody');
      lh.pages.forEach(function (p) {
        var tr = el('tr'); tr.appendChild(el('td', null, p.path));
        ['performance', 'accessibility', 'best-practices', 'seo'].forEach(function (c) {
          var s = Math.round((p.scores[c] || 0) * 100), td = el('td', { class: 'num' });
          td.appendChild(el('span', { class: 'score ' + (s >= 90 ? 'good' : s >= 50 ? 'warn' : 'bad') }, String(s))); tr.appendChild(td);
        });
        tr.appendChild(el('td', { class: 'num' }, p.lcp)); tr.appendChild(el('td', { class: 'num' }, p.cls)); tr.appendChild(el('td', { class: 'num' }, p.tbt));
        b2.appendChild(tr);
      });
      t2.appendChild(b2); var w = el('div', { class: 'table-wrap' }); w.appendChild(t2); lhBox.appendChild(w);
      if (lh.note) lhBox.appendChild(el('p', { class: 'method' }, lh.note));
    } else lhBox.appendChild(el('p', { class: 'empty' }, 'Pas encore de mesure Lighthouse : elle tourne chaque semaine et après chaque modification du site.'));
    A.mount([
      A.section('Visites réelles, 28 derniers jours', real),
      el('p', { class: 'method' }, 'p75 : 75 % des visites sont plus rapides que cette valeur ; c’est le critère de Google. Seuils « bons » : LCP ≤ 2,5 s, INP ≤ 200 ms, CLS ≤ 0,1.'),
      A.section('Lighthouse (laboratoire)', lhBox)]);
  }).catch(function () { A.mount([el('p', { class: 'notice' }, 'Données indisponibles.')]); });
});
