// Public visitor numbers (daily totals only), drawn as an accessible SVG bar chart.
(function () {
  var box = document.getElementById('visiteurs');
  if (!box || !window.fetch) return;
  var locale = box.getAttribute('data-locale') || 'fr-CH';
  var nf = new Intl.NumberFormat(locale);
  var state = document.getElementById('etat-visiteurs'), graph = document.getElementById('graphe-visiteurs');
  var NS = 'http://www.w3.org/2000/svg';
  function el(name, attrs, text) {
    var e = document.createElementNS(NS, name);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (text !== undefined) e.textContent = text;
    return e;
  }
  fetch('/api/visitors', { credentials: 'same-origin' }).then(function (r) { if (!r.ok) throw 0; return r.json(); }).then(function (d) {
    box.querySelector('[data-stat="total"]').textContent = nf.format(d.total || 0);
    box.querySelector('[data-stat="last30"]').textContent = nf.format(d.last30 || 0);
    box.querySelector('[data-stat="today"]').textContent = nf.format(d.today || 0);
    var days = d.daily || [];
    state.textContent = '';
    if (!days.length) return;
    var W = 720, H = 220, L = 44, B = 32, T = 16, max = Math.max.apply(null, days.map(function (x) { return x.n; })) || 1;
    var title = graph.getAttribute('data-title');
    var svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, class: 'chart', role: 'img', 'aria-label': title });
    svg.appendChild(el('title', {}, title));
    var bw = (W - L - 8) / days.length;
    [0, 0.5, 1].forEach(function (f) {
      var y = T + (H - T - B) * (1 - f);
      svg.appendChild(el('line', { class: 'grid', x1: L, x2: W - 8, y1: y, y2: y }));
      svg.appendChild(el('text', { class: 'tick', x: L - 6, y: y + 4, 'text-anchor': 'end' }, nf.format(Math.round(max * f))));
    });
    days.forEach(function (x, i) {
      var h = (H - T - B) * x.n / max, xPos = L + i * bw + bw * 0.15, label = x.day.slice(8, 10) + '.' + x.day.slice(5, 7);
      var r = el('rect', { class: 'bar hl', x: xPos, y: T + (H - T - B) - h, width: bw * 0.7, height: Math.max(h, 1), rx: 2 });
      r.appendChild(el('title', {}, label + ' : ' + nf.format(x.n)));
      svg.appendChild(r);
      if (i % Math.max(1, Math.round(days.length / 6)) === 0) svg.appendChild(el('text', { class: 'tick', x: xPos + bw * 0.35, y: H - 10, 'text-anchor': 'middle' }, label));
    });
    graph.appendChild(svg);
    // Text alternative
    var det = document.createElement('details'); det.className = 'chart-data';
    var sum = document.createElement('summary'); sum.textContent = graph.getAttribute('data-show') || title;
    det.appendChild(sum);
    var tbl = document.createElement('table'), tb = document.createElement('tbody');
    days.slice().reverse().forEach(function (x) {
      var tr = document.createElement('tr'), a = document.createElement('td'), b = document.createElement('td');
      a.textContent = x.day; b.textContent = nf.format(x.n); b.className = 'num'; tr.appendChild(a); tr.appendChild(b); tb.appendChild(tr);
    });
    tbl.appendChild(tb); det.appendChild(tbl); graph.appendChild(det);
  }).catch(function () {
    var t = document.getElementById('txt-unavailable'); state.textContent = t ? t.textContent : '';
  });
})();
