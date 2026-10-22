// Comments under each bulletin: list, post (moderated), like a comment.
// Cloudflare Turnstile is loaded only when the visitor interacts, so it never slows the page.
(function () {
  var box = document.getElementById('commentaires');
  if (!box || !window.fetch) return;
  var thread = box.getAttribute('data-thread'), lang = box.getAttribute('data-lang') || 'fr';
  var siteKey = box.getAttribute('data-sitekey') || '';
  var TXT = {
    fr: { loading: 'Chargement des commentaires…', none: 'Aucun commentaire pour l’instant.', unavailable: 'Commentaires momentanément indisponibles.',
      sent: 'Merci ! Votre commentaire sera publié après relecture.', sending: 'Envoi…', name: 'Indiquez un nom d’au moins 2 caractères.',
      short: 'Écrivez au moins 20 caractères, en quelques mots.', captcha: 'Le contrôle anti-robot a échoué. Réessayez.',
      wait: 'Confirmez que vous n’êtes pas un robot ci-dessus, puis envoyez.', rate: 'Trop d’envois récents. Réessayez dans quelques minutes.',
      error: 'Envoi impossible pour le moment.', off: 'Les commentaires seront ouverts prochainement.', like: 'J’aime le commentaire de', likes: 'mentions j’aime',
      human: 'Pour aimer un commentaire, confirmez d’abord que vous n’êtes pas un robot :', count: function (n) { return '(' + n + ')'; } },
    de: { loading: 'Kommentare werden geladen…', none: 'Noch keine Kommentare.', unavailable: 'Kommentare vorübergehend nicht verfügbar.',
      sent: 'Danke! Ihr Kommentar erscheint nach der Prüfung.', sending: 'Wird gesendet…', name: 'Geben Sie einen Namen mit mindestens 2 Zeichen ein.',
      short: 'Schreiben Sie mindestens 20 Zeichen, in ein paar Worten.', captcha: 'Die Roboterprüfung ist fehlgeschlagen. Bitte erneut versuchen.',
      wait: 'Bestätigen Sie oben, dass Sie kein Roboter sind, und senden Sie dann.', rate: 'Zu viele Einsendungen. Bitte in einigen Minuten erneut versuchen.',
      error: 'Senden im Moment nicht möglich.', off: 'Die Kommentare werden demnächst geöffnet.', like: 'Gefällt mir: Kommentar von', likes: 'Gefällt-mir-Angaben',
      human: 'Um einen Kommentar zu markieren, bestätigen Sie zuerst, dass Sie kein Roboter sind:', count: function (n) { return '(' + n + ')'; } },
    it: { loading: 'Caricamento dei commenti…', none: 'Ancora nessun commento.', unavailable: 'Commenti momentaneamente non disponibili.',
      sent: 'Grazie! Il vostro commento sarà pubblicato dopo la lettura.', sending: 'Invio…', name: 'Indicate un nome di almeno 2 caratteri.',
      short: 'Scrivete almeno 20 caratteri, in qualche parola.', captcha: 'Il controllo anti-robot non è riuscito. Riprovate.',
      wait: 'Confermate qui sopra di non essere un robot, poi inviate.', rate: 'Troppi invii recenti. Riprovate tra qualche minuto.',
      error: 'Invio impossibile al momento.', off: 'I commenti saranno aperti a breve.', like: 'Mi piace il commento di', likes: 'mi piace',
      human: 'Per mettere «mi piace», confermate prima di non essere un robot:', count: function (n) { return '(' + n + ')'; } },
    en: { loading: 'Loading comments…', none: 'No comments yet.', unavailable: 'Comments are temporarily unavailable.',
      sent: 'Thank you! Your comment will appear once it has been reviewed.', sending: 'Sending…', name: 'Enter a name of at least 2 characters.',
      short: 'Write at least 20 characters, in a few words.', captcha: 'The bot check failed. Please try again.',
      wait: 'Confirm above that you are not a robot, then send.', rate: 'Too many recent posts. Please try again in a few minutes.',
      error: 'Sending is not possible right now.', off: 'Comments will open soon.', like: 'Like the comment by', likes: 'likes',
      human: 'To like a comment, first confirm that you are not a robot:', count: function (n) { return '(' + n + ')'; } }
  }[lang];
  var LOCALE = { fr: 'fr-CH', de: 'de-CH', it: 'it-CH', en: 'en-GB' }[lang];
  var THUMB = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M7 10v10H4V10h3zm0 0l4-7c1.7 0 2.6 1.1 2.3 2.7L12.8 9H19a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 17.8 20H7"/></svg>';
  var list = document.getElementById('liste-commentaires'), state = document.getElementById('etat-commentaires');
  var countEl = document.getElementById('nb-commentaires'), form = document.getElementById('form-commentaire');
  var msg = document.getElementById('c-message'), widgetBox = document.getElementById('turnstile');
  var nf = new Intl.NumberFormat(LOCALE), df = new Intl.DateTimeFormat(LOCALE, { dateStyle: 'long', timeStyle: 'short', timeZone: 'Europe/Zurich' });

  function api(path, opts) {
    opts = opts || {};
    return fetch(path, { method: opts.method || 'GET', credentials: 'same-origin',
      headers: opts.body ? { 'Content-Type': 'application/json' } : {}, body: opts.body ? JSON.stringify(opts.body) : undefined })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { d._status = r.status; return d; }); });
  }

  // ---- Turnstile, loaded on demand
  var tsPromise = null;
  function loadTurnstile() {
    if (tsPromise) return tsPromise;
    tsPromise = new Promise(function (resolve, reject) {
      window.tpTurnstileReady = function () { resolve(window.turnstile); };
      var s = document.createElement('script');
      s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit&onload=tpTurnstileReady';
      s.async = true; s.onerror = reject; document.head.appendChild(s);
    });
    return tsPromise;
  }
  function renderWidget(el, onToken) {
    return loadTurnstile().then(function (ts) {
      return ts.render(el, { sitekey: siteKey, language: lang, theme: 'auto', size: 'flexible',
        callback: onToken, 'expired-callback': function () { onToken(''); }, 'error-callback': function () { onToken(''); return true; } });
    });
  }

  // ---- List
  var total = 0;
  function setCount() { countEl.textContent = total ? TXT.count(total) : ''; state.textContent = total ? '' : TXT.none; }
  function render(c) {
    var li = document.createElement('li'); li.className = 'comment'; li.id = 'commentaire-' + c.id;
    var head = document.createElement('p'); head.className = 'comment-head';
    var b = document.createElement('strong'); b.textContent = c.name;
    var time = document.createElement('time'); time.dateTime = c.created_at; time.textContent = df.format(new Date(c.created_at));
    head.appendChild(b); head.appendChild(time);
    var body = document.createElement('p'); body.className = 'comment-body'; body.textContent = c.message;
    if (c.lang && c.lang !== lang) body.lang = c.lang;
    li.appendChild(head); li.appendChild(body); li.appendChild(likeButton(c));
    list.appendChild(li);
  }
  function likeButton(c) {
    var btn = document.createElement('button'); btn.type = 'button'; btn.className = 'like';
    var likes = c.likes || 0, liked = !!c.liked;
    btn.innerHTML = THUMB;
    var sr = document.createElement('span'); sr.className = 'sr-only'; sr.textContent = TXT.like + ' ' + c.name + ', ';
    var nb = document.createElement('span'); var unit = document.createElement('span'); unit.className = 'sr-only';
    btn.appendChild(sr); btn.appendChild(nb); btn.appendChild(unit);
    function show() { nb.textContent = nf.format(likes); unit.textContent = ' ' + TXT.likes; btn.setAttribute('aria-pressed', String(liked)); }
    show();
    btn.addEventListener('click', function () {
      btn.disabled = true;
      api('/api/comments/like', { method: 'POST', body: { id: c.id } }).then(function (d) {
        if (d._status === 403 && d.error === 'human') return askHuman(btn).then(function () { btn.disabled = false; btn.click(); });
        if (d._status === 200) { likes = d.likes; liked = d.liked; show(); }
      }).catch(function () {}).then(function () { btn.disabled = false; });
    });
    return btn;
  }
  // One bot check per visit unlocks likes (the server then sets a short-lived signed cookie).
  var humanBox = null, humanPromise = null;
  function askHuman(nearBtn) {
    if (humanPromise) return humanPromise;
    humanBox = document.createElement('div'); humanBox.className = 'block';
    var p = document.createElement('p'); p.textContent = TXT.human; humanBox.appendChild(p);
    var w = document.createElement('div'); humanBox.appendChild(w);
    nearBtn.closest('li').appendChild(humanBox);
    humanPromise = new Promise(function (resolve) {
      renderWidget(w, function (token) {
        if (!token) return;
        api('/api/human', { method: 'POST', body: { token: token } }).then(function (d) {
          if (d._status === 200) { humanBox.remove(); resolve(); }
        });
      });
    });
    return humanPromise;
  }

  state.textContent = TXT.loading;
  api('/api/comments?thread=' + encodeURIComponent(thread)).then(function (d) {
    if (d._status !== 200) throw 0;
    total = d.comments.length; d.comments.forEach(render); setCount();
  }).catch(function () { state.textContent = TXT.unavailable; });

  // ---- Form
  var name = document.getElementById('c-nom'), text = document.getElementById('c-texte');
  if (!siteKey) {
    form.querySelectorAll('input, textarea, button').forEach(function (el) { el.disabled = true; });
    msg.textContent = TXT.off; return;
  }
  var token = '', widgetId = null, started = false;
  function startWidget() {
    if (started) return; started = true;
    renderWidget(widgetBox, function (t) { token = t; }).then(function (id) { widgetId = id; });
  }
  form.addEventListener('focusin', startWidget);
  function fail(field, t) {
    msg.className = 'form-message erreur'; msg.textContent = t;
    if (field) { field.setAttribute('aria-invalid', 'true'); field.focus(); }
  }
  [name, text].forEach(function (f) { f.addEventListener('input', function () { f.removeAttribute('aria-invalid'); }); });
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    startWidget();
    var n = name.value.trim(), m = text.value.trim();
    if (n.length < 2) return fail(name, TXT.name);
    if (m.length < 20 || m.split(/\s+/).length < 3) return fail(text, TXT.short);
    if (!token) return fail(null, TXT.wait);
    var btn = form.querySelector('button[type=submit]'); btn.disabled = true;
    msg.className = 'form-message'; msg.textContent = TXT.sending;
    api('/api/comments', { method: 'POST', body: { thread: thread, lang: lang, name: n, message: m, token: token,
      website: document.getElementById('c-site').value } }).then(function (d) {
      if (d._status === 201) { form.reset(); msg.className = 'form-message ok'; msg.textContent = TXT.sent; return; }
      var map = { name: [name, TXT.name], empty: [text, TXT.short], captcha: [null, TXT.captcha], rate: [null, TXT.rate] };
      var f = map[d.error] || [null, TXT.error]; fail(f[0], f[1]);
    }).catch(function () { fail(null, TXT.error); }).then(function () {
      btn.disabled = false; token = '';
      if (window.turnstile && widgetId !== null) window.turnstile.reset(widgetId);
    });
  });
})();
