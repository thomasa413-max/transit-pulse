// Transit Pulse 3D map: MapLibre, OpenFreeMap tiles, real sun lighting over Lausanne,
// stop punctuality as 3D columns, disruption pins, weather from our Worker.
(function () {
  var box = document.getElementById('carte');
  if (!box) return;
  var T = JSON.parse(document.getElementById('carte-i18n').textContent);
  var lang = T.lang, status = document.getElementById('carte-etat');
  var nf = new Intl.NumberFormat(T.locale, { maximumFractionDigits: 1 });
  var LAUSANNE = [6.6323, 46.5197];

  function webgl() {
    try { var c = document.createElement('canvas'); return !!(c.getContext('webgl2') || c.getContext('webgl')); } catch (e) { return false; }
  }
  if (!window.maplibregl || !webgl()) { status.textContent = T.map_nowebgl; return; }

  // ---------------------------------------------------------------- sun position (SunCalc formulas)
  function sun(date, lat, lon) {
    var rad = Math.PI / 180, d = date / 86400000 - 0.5 + 2440588 - 2451545, e = rad * 23.4397;
    var M = rad * (357.5291 + 0.98560028 * d);
    var L = M + rad * (1.9148 * Math.sin(M) + 0.02 * Math.sin(2 * M) + 0.0003 * Math.sin(3 * M)) + rad * 102.9372 + Math.PI;
    var dec = Math.asin(Math.sin(e) * Math.sin(L)), ra = Math.atan2(Math.sin(L) * Math.cos(e), Math.cos(L));
    var H = rad * (280.16 + 360.9856235 * d) + rad * lon - ra, phi = rad * lat;
    var alt = Math.asin(Math.sin(phi) * Math.sin(dec) + Math.cos(phi) * Math.cos(dec) * Math.cos(H));
    var az = Math.atan2(Math.sin(H), Math.cos(H) * Math.sin(phi) - Math.tan(dec) * Math.cos(phi));
    return { alt: alt / rad, az: (az / rad + 180) % 360 };   // degrees; azimuth from north
  }

  // ---------------------------------------------------------------- palettes
  var DAY = { bg: '#eef0e6', water: '#9cc6e4', park: '#cfe3b8', wood: '#b8d6a0', residential: '#e7e5dd', road: '#ffffff',
    roadMajor: '#f6d58e', rail: '#9a9a9a', building: '#d9d4c7', building3d: '#e2ddd0', label: '#3a3f45', halo: '#ffffff',
    sky: '#8ec5ef', horizon: '#dcecf7', fog: '#eef3f6', hill: '#6b7280' };
  var NIGHT = { bg: '#0f141b', water: '#0b2234', park: '#13241a', wood: '#112117', residential: '#151a22', road: '#3b4250',
    roadMajor: '#7a6431', rail: '#4b5563', building: '#1d222b', building3d: '#272d38', label: '#cfd6df', halo: '#0b0f14',
    sky: '#05070d', horizon: '#1b2740', fog: '#101622', hill: '#000000' };
  function hex(c) { return [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)]; }
  function mix(a, b, t) {
    var x = hex(a), y = hex(b);
    return '#' + x.map(function (v, i) { return Math.round(v + (y[i] - v) * t).toString(16).padStart(2, '0'); }).join('');
  }
  function palette(t) { var p = {}; for (var k in DAY) p[k] = mix(DAY[k], NIGHT[k], t); return p; }

  // ---------------------------------------------------------------- style
  var name = ['coalesce', ['get', 'name:' + lang], ['get', 'name']];
  var P = palette(0);
  var style = {
    version: 8,
    glyphs: 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf',
    sources: {
      omt: { type: 'vector', url: 'https://tiles.openfreemap.org/planet', attribution: '© OpenFreeMap © OpenMapTiles © OpenStreetMap' },
      dem: { type: 'raster-dem', tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],
        encoding: 'terrarium', tileSize: 256, maxzoom: 14, attribution: 'Terrain: Mapzen / AWS' },
      stops: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } },
      pins: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } }
    },
    layers: [
      { id: 'bg', type: 'background', paint: { 'background-color': P.bg } },
      { id: 'residential', type: 'fill', source: 'omt', 'source-layer': 'landuse', filter: ['==', ['get', 'class'], 'residential'], paint: { 'fill-color': P.residential } },
      { id: 'wood', type: 'fill', source: 'omt', 'source-layer': 'landcover', filter: ['in', ['get', 'class'], ['literal', ['wood', 'forest']]], paint: { 'fill-color': P.wood } },
      { id: 'park', type: 'fill', source: 'omt', 'source-layer': 'park', paint: { 'fill-color': P.park } },
      { id: 'grass', type: 'fill', source: 'omt', 'source-layer': 'landcover', filter: ['==', ['get', 'class'], 'grass'], paint: { 'fill-color': P.park, 'fill-opacity': 0.7 } },
      { id: 'hillshade', type: 'hillshade', source: 'dem', paint: { 'hillshade-shadow-color': P.hill, 'hillshade-exaggeration': 0.35 } },
      { id: 'water', type: 'fill', source: 'omt', 'source-layer': 'water', paint: { 'fill-color': P.water } },
      { id: 'waterway', type: 'line', source: 'omt', 'source-layer': 'waterway', paint: { 'line-color': P.water, 'line-width': 1.5 } },
      { id: 'road-minor', type: 'line', source: 'omt', 'source-layer': 'transportation', minzoom: 12,
        filter: ['in', ['get', 'class'], ['literal', ['minor', 'service', 'track', 'path']]],
        paint: { 'line-color': P.road, 'line-width': ['interpolate', ['linear'], ['zoom'], 13, 0.5, 18, 6] } },
      { id: 'road-major', type: 'line', source: 'omt', 'source-layer': 'transportation',
        filter: ['in', ['get', 'class'], ['literal', ['motorway', 'trunk', 'primary', 'secondary', 'tertiary']]],
        paint: { 'line-color': P.roadMajor, 'line-width': ['interpolate', ['linear'], ['zoom'], 10, 1, 18, 12] } },
      { id: 'rail', type: 'line', source: 'omt', 'source-layer': 'transportation', filter: ['==', ['get', 'class'], 'rail'],
        paint: { 'line-color': P.rail, 'line-width': ['interpolate', ['linear'], ['zoom'], 11, 1, 18, 3], 'line-dasharray': [3, 2] } },
      { id: 'building', type: 'fill', source: 'omt', 'source-layer': 'building', maxzoom: 14, paint: { 'fill-color': P.building } },
      { id: 'building-3d', type: 'fill-extrusion', source: 'omt', 'source-layer': 'building', minzoom: 13.5,
        paint: { 'fill-extrusion-color': P.building3d, 'fill-extrusion-opacity': 0.92,
          'fill-extrusion-height': ['coalesce', ['get', 'render_height'], 8],
          'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], 0], 'fill-extrusion-vertical-gradient': true } },
      { id: 'stops-3d', type: 'fill-extrusion', source: 'stops',
        paint: { 'fill-extrusion-color': ['step', ['get', 'pct'], '#d7301f', 80, '#f28e2b', 95, '#2ca25f'],
          'fill-extrusion-height': ['get', 'h'], 'fill-extrusion-base': 0, 'fill-extrusion-opacity': 0.95 } },
      { id: 'pins', type: 'circle', source: 'pins',
        paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 11, 6, 17, 11], 'circle-color': ['case', ['get', 'planned'], '#f2b134', '#e4572e'],
          'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2.5, 'circle-pitch-alignment': 'viewport' } },
      { id: 'place-label', type: 'symbol', source: 'omt', 'source-layer': 'place',
        filter: ['in', ['get', 'class'], ['literal', ['city', 'town', 'village', 'suburb', 'quarter', 'neighbourhood']]],
        layout: { 'text-field': name, 'text-font': ['Noto Sans Regular'], 'text-size': ['interpolate', ['linear'], ['zoom'], 11, 11, 16, 15] },
        paint: { 'text-color': P.label, 'text-halo-color': P.halo, 'text-halo-width': 1.5 } },
      { id: 'water-label', type: 'symbol', source: 'omt', 'source-layer': 'water_name',
        layout: { 'text-field': name, 'text-font': ['Noto Sans Italic'], 'text-size': 13 },
        paint: { 'text-color': '#4a7ba6', 'text-halo-color': P.halo, 'text-halo-width': 1 } }
    ]
  };

  status.textContent = '';
  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var small = window.innerWidth < 700;
  var map = new maplibregl.Map({
    container: box, style: style, center: LAUSANNE, zoom: small ? 13.4 : 14.2, pitch: 60, bearing: -24, maxPitch: 75,
    minZoom: 10, maxBounds: [[6.2, 46.25], [7.2, 46.85]], attributionControl: { compact: true }, locale: {},
    cooperativeGestures: small, fadeDuration: reduceMotion ? 0 : 300
  });
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
  map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left');

  // ---------------------------------------------------------------- light, sky and colours
  var lightMode = 'auto';
  function nightFactor(alt) { return alt >= 6 ? 0 : alt <= -6 ? 1 : (6 - alt) / 12; }
  function applyLight() {
    var s = sun(Date.now(), LAUSANNE[1], LAUSANNE[0]);
    var alt = lightMode === 'day' ? 35 : lightMode === 'night' ? -20 : s.alt;
    var az = lightMode === 'auto' ? s.az : 200;
    var k = nightFactor(alt), p = palette(k);
    [['bg', 'background-color', 'bg'], ['residential', 'fill-color', 'residential'], ['wood', 'fill-color', 'wood'],
     ['park', 'fill-color', 'park'], ['grass', 'fill-color', 'park'], ['water', 'fill-color', 'water'], ['waterway', 'line-color', 'water'],
     ['road-minor', 'line-color', 'road'], ['road-major', 'line-color', 'roadMajor'], ['rail', 'line-color', 'rail'],
     ['building', 'fill-color', 'building'], ['building-3d', 'fill-extrusion-color', 'building3d'], ['hillshade', 'hillshade-shadow-color', 'hill'],
     ['place-label', 'text-color', 'label'], ['place-label', 'text-halo-color', 'halo'], ['water-label', 'text-halo-color', 'halo']]
      .forEach(function (x) { if (map.getLayer(x[0])) map.setPaintProperty(x[0], x[1], p[x[2]]); });
    map.setLight({ anchor: 'map', position: [1.5, az, Math.max(12, Math.min(88, 90 - Math.max(alt, 5)))],
      color: k > 0.5 ? '#9fb3d9' : '#fff6e5', intensity: k > 0.5 ? 0.25 : 0.45 });
    if (map.setSky) map.setSky({ 'sky-color': p.sky, 'horizon-color': p.horizon, 'fog-color': p.fog,
      'sky-horizon-blend': 0.6, 'horizon-fog-blend': 0.5, 'fog-ground-blend': 0.6, 'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 10, 1, 15, 0.4] });
    box.classList.toggle('is-night', k > 0.5);
  }

  // ---------------------------------------------------------------- data
  function circle(lon, lat, radiusM, sides) {
    var pts = [], dLat = radiusM / 111320, dLon = radiusM / (111320 * Math.cos(lat * Math.PI / 180));
    for (var i = 0; i <= sides; i++) { var a = 2 * Math.PI * i / sides; pts.push([lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)]); }
    return [pts];
  }
  var stopsById = {};
  function loadData() {
    return fetch(box.getAttribute('data-src'), { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (d) {
      var features = d.arrets.map(function (s) {
        stopsById[String(s.id)] = s;
        return { type: 'Feature', id: s.id, properties: { id: String(s.id), pct: s.pct, h: Math.min(260, 25 + (100 - s.pct) * 7) },
          geometry: { type: 'Polygon', coordinates: circle(s.lon, s.lat, 14, 14) } };
      });
      map.getSource('stops').setData({ type: 'FeatureCollection', features: features });
      map.getSource('pins').setData({ type: 'FeatureCollection', features: d.perturbations.map(function (p) {
        return { type: 'Feature', properties: { title: (p.textes && p.textes[lang]) || '', place: p.lieu, planned: !!p.planifie },
          geometry: { type: 'Point', coordinates: [p.lon, p.lat] } };
      }) });
    });
  }

  // ---------------------------------------------------------------- popups (DOM, never HTML strings)
  var popup = new maplibregl.Popup({ closeButton: true, maxWidth: '280px', className: 'tp-popup' });
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function stopPopup(s) {
    var div = el('div');
    div.appendChild(el('p', 'pp-title', s.nom));
    var pctText = nf.format(s.pct) + (lang === 'en' || lang === 'it' ? '%' : ' %');
    [[T.col_ontime, pctText], [T.col_delay, s.retard == null ? '–' : nf.format(s.retard) + ' ' + T.min],
     [T.col_measured, nf.format(s.mesures)], [T.col_cancel, nf.format(s.supprimes)], [T.col_lines, (s.lignes || []).slice(0, 8).join(', ')]]
      .forEach(function (r) { var p = el('p', 'pp-row'); p.appendChild(el('span', 'pp-k', r[0])); p.appendChild(el('span', 'pp-v', r[1])); div.appendChild(p); });
    return div;
  }
  function showStop(s) { popup.setLngLat([s.lon, s.lat]).setDOMContent(stopPopup(s)).addTo(map); }
  map.on('click', 'stops-3d', function (e) { var s = stopsById[e.features[0].properties.id]; if (s) showStop(s); });
  map.on('click', 'pins', function (e) {
    var f = e.features[0].properties, div = el('div');
    div.appendChild(el('p', 'pp-kind', f.planned === true || f.planned === 'true' ? T.disr_planned : T.disr_unplanned));
    div.appendChild(el('p', 'pp-title', f.title)); div.appendChild(el('p', 'muted', f.place));
    popup.setLngLat(e.lngLat).setDOMContent(div).addTo(map);
  });
  ['stops-3d', 'pins'].forEach(function (id) {
    map.on('mouseenter', id, function () { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', id, function () { map.getCanvas().style.cursor = ''; });
  });

  // ---------------------------------------------------------------- controls
  function bindToggle(id, fn) {
    var b = document.getElementById(id); if (!b) return;
    b.addEventListener('click', function () { var on = b.getAttribute('aria-pressed') !== 'true'; b.setAttribute('aria-pressed', String(on)); fn(on); });
  }
  function vis(layer, on) { if (map.getLayer(layer)) map.setLayoutProperty(layer, 'visibility', on ? 'visible' : 'none'); }
  bindToggle('t-stops', function (on) { vis('stops-3d', on); });
  bindToggle('t-disr', function (on) { vis('pins', on); });
  bindToggle('t-buildings', function (on) { vis('building-3d', on); vis('building', !on); });
  bindToggle('t-terrain', function (on) { map.setTerrain(on ? { source: 'dem', exaggeration: 1.25 } : null); vis('hillshade', on); });
  bindToggle('t-2d', function (on) { map.easeTo({ pitch: on ? 0 : 60, bearing: on ? 0 : -24, duration: reduceMotion ? 0 : 800 }); });
  document.querySelectorAll('[data-light]').forEach(function (b) {
    b.addEventListener('click', function () {
      lightMode = b.getAttribute('data-light');
      document.querySelectorAll('[data-light]').forEach(function (x) { x.setAttribute('aria-pressed', String(x === b)); });
      applyLight();
    });
  });
  document.querySelectorAll('[data-fly]').forEach(function (b) {
    b.addEventListener('click', function () {
      var s = stopsById[b.getAttribute('data-fly')]; if (!s) return;
      box.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'center' });
      map.flyTo({ center: [s.lon, s.lat], zoom: 16.2, pitch: 55, duration: reduceMotion ? 0 : 1600 });
      map.once('moveend', function () { showStop(s); map.getCanvas().focus(); });
    });
  });

  // ---------------------------------------------------------------- weather (through our Worker, cached)
  var WMO = {
    fr: { 0: 'Ciel dégagé', 1: 'Plutôt dégagé', 2: 'Partiellement nuageux', 3: 'Couvert', 45: 'Brouillard', 51: 'Bruine', 61: 'Pluie', 71: 'Neige', 80: 'Averses', 95: 'Orage' },
    de: { 0: 'Klar', 1: 'Überwiegend klar', 2: 'Teilweise bewölkt', 3: 'Bedeckt', 45: 'Nebel', 51: 'Nieselregen', 61: 'Regen', 71: 'Schnee', 80: 'Schauer', 95: 'Gewitter' },
    it: { 0: 'Sereno', 1: 'Prevalentemente sereno', 2: 'Parzialmente nuvoloso', 3: 'Coperto', 45: 'Nebbia', 51: 'Pioviggine', 61: 'Pioggia', 71: 'Neve', 80: 'Rovesci', 95: 'Temporale' },
    en: { 0: 'Clear sky', 1: 'Mainly clear', 2: 'Partly cloudy', 3: 'Overcast', 45: 'Fog', 51: 'Drizzle', 61: 'Rain', 71: 'Snow', 80: 'Showers', 95: 'Thunderstorm' }
  }[lang];
  function describe(code) {
    var keys = [95, 80, 71, 61, 51, 45, 3, 2, 1, 0];
    for (var i = 0; i < keys.length; i++) if (code >= keys[i]) return WMO[keys[i]];
    return '';
  }
  fetch('/api/weather', { credentials: 'same-origin' }).then(function (r) { if (!r.ok) throw 0; return r.json(); }).then(function (w) {
    var c = w.current || {}, box2 = document.getElementById('meteo');
    box2.textContent = '';
    box2.appendChild(el('p', 'legend-title', T.map_weather));
    var big = el('p', 'weather-now', nf.format(Math.round(c.temperature_2m)) + ' °C');
    box2.appendChild(big);
    box2.appendChild(el('p', null, describe(c.weather_code) + ' · ' + nf.format(Math.round(c.wind_speed_10m)) + ' km/h'));
    if (c.weather_code >= 45 && map.setSky) box.classList.add('is-hazy');
  }).catch(function () {});

  map.on('load', function () {
    applyLight();
    loadData().catch(function () {});
    if (!small) { map.setTerrain({ source: 'dem', exaggeration: 1.25 }); } else {
      var tb = document.getElementById('t-terrain'); if (tb) tb.setAttribute('aria-pressed', 'false'); vis('hillshade', false);
    }
    setInterval(function () { if (lightMode === 'auto') applyLight(); }, 5 * 60 * 1000);
  });
  map.on('error', function (e) { if (e && e.error && /WebGL/i.test(String(e.error.message))) status.textContent = T.map_nowebgl; });
})();
