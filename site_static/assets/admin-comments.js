// Moderation: approve, hide or delete comments. Text is always inserted with textContent (never as HTML).
TPAdmin.ready(function () {
  var A = TPAdmin, el = A.el, filter = 'pending';
  var LABEL = { pending: 'En attente', approved: 'Publiés', hidden: 'Masqués', all: 'Tous' };
  var df = new Intl.DateTimeFormat('fr-CH', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Europe/Zurich' });
  function load() {
    A.api('/api/admin/comments' + (filter === 'all' ? '' : '?status=' + filter)).then(function (d) {
      var filters = el('div', { class: 'adm-filters', role: 'group', 'aria-label': 'Filtrer' });
      Object.keys(LABEL).forEach(function (k) {
        var b = el('button', { type: 'button', class: 'tool', 'aria-pressed': String(k === filter) }, LABEL[k]);
        b.addEventListener('click', function () { filter = k; load(); });
        filters.appendChild(b);
      });
      var list = el('div');
      if (!d.comments.length) list.appendChild(el('p', { class: 'empty' }, 'Aucun commentaire dans cette catégorie.'));
      d.comments.forEach(function (c) {
        var item = el('article', { class: 'adm-comment' });
        var meta = [df.format(new Date(c.created_at)), 'bulletin du ' + c.thread, 'langue : ' + c.lang, A.country(c.country),
          c.ip ? 'IP ' + c.ip : 'IP effacée', c.likes + ' j’aime', LABEL[c.status] || c.status].join(' · ');
        item.appendChild(el('p', { class: 'adm-meta' }, meta));
        item.appendChild(el('h3', null, c.name));
        var body = el('p', { class: 'comment-body' }, c.message); body.lang = c.lang; item.appendChild(body);
        var actions = el('div', { class: 'adm-actions' });
        function action(label, fn, cls) { var b = el('button', { type: 'button', class: 'tool ' + (cls || '') }, label); b.addEventListener('click', fn); actions.appendChild(b); }
        var page = { fr: '/fr/bulletin/', de: '/de/bulletin/', it: '/it/bollettino/', en: '/en/bulletin/' }[c.lang] || '/fr/bulletin/';
        if (c.status !== 'approved') action('Publier', function () { send('POST', { id: c.id, action: 'approve' }); });
        if (c.status !== 'hidden') action('Masquer', function () { send('POST', { id: c.id, action: 'hide' }); });
        action('Supprimer définitivement', function () {
          if (window.confirm('Supprimer définitivement le commentaire de « ' + c.name + ' » ?')) send('DELETE', { id: c.id });
        }, 'danger');
        var see = el('a', { href: page + c.thread + '/#commentaires', class: 'tool' }, 'Voir la page'); actions.appendChild(see);
        item.appendChild(actions); list.appendChild(item);
      });
      A.mount([filters, A.section(LABEL[filter] + ' (' + d.comments.length + ')', list)]);
    });
  }
  function send(method, body) { A.api('/api/admin/comments', { method: method, body: body }).then(function () { load(); A.refreshBadge(); }); }
  load();
});
