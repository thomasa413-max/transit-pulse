// Administration home: what needs attention today.
TPAdmin.ready(function () {
  var A = TPAdmin, el = A.el;
  A.api('/api/admin/summary').then(function (d) {
    var tiles = el('div', { class: 'tiles' });
    function tile(label, value, note, href) {
      var t = el('div', { class: 'tile' + (href && value ? ' accent' : '') });
      t.appendChild(el('p', { class: 'tile-label' }, label));
      var v = el('p', { class: 'tile-value' });
      if (href) { var a = el('a', { href: href }, String(value)); v.appendChild(a); } else v.textContent = value;
      t.appendChild(v); if (note) t.appendChild(el('p', { class: 'tile-note' }, note));
      tiles.appendChild(t);
    }
    tile('Commentaires en attente', d.pending, 'À valider avant publication', '/admin/commentaires/');
    tile('Visiteurs aujourd’hui', A.nf.format(d.visitorsToday));
    tile('Visiteurs ce mois-ci', A.nf.format(d.visitorsMonth));
    var lcp = d.vitals['LCP.mobile'];
    tile('LCP mobile (p75, 28 j)', lcp ? (lcp.p75 === null ? '> 10 s' : (lcp.p75 / 1000).toFixed(1).replace('.', ',') + ' s') : '–',
      lcp ? Math.round(lcp.good * 100) + ' % de visites « bonnes »' : 'Pas encore de mesure');
    var links = el('ul', { class: 'plain' });
    [['Journal des agents (public)', '/fr/agents/'], ['Exécutions GitHub Actions', 'https://github.com/thomasa413-max/transit-pulse/actions'],
     ['Tableau de bord Cloudflare', 'https://dash.cloudflare.com/'], ['Console Claude (coûts API)', 'https://platform.claude.com/'],
     ['Search Console (après la mise en ligne)', 'https://search.google.com/search-console']].forEach(function (l) {
      var li = el('li'); li.appendChild(el('a', { href: l[1] }, l[0])); links.appendChild(li);
    });
    A.mount([tiles,
      A.section('Pays (30 jours)', A.bars(d.countries, A.country)),
      A.section('Provenance (30 jours)', A.bars(d.referrers)),
      A.section('Liens utiles', links)]);
  }).catch(function () { A.mount([el('p', { class: 'notice' }, 'Données indisponibles.')]); });
});
