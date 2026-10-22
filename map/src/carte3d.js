// Transit Pulse 3D map: CesiumJS engine with swisstopo's official 3D data
// (swissBUILDINGS3D, swissALTI3D terrain, SWISSIMAGE aerial photos), real sun position over Lausanne,
// stop punctuality as 3D columns, disruption pins and weather from our Worker.
/* global __CESIUM_BASE__ */
import {
  Cartesian2, Cartesian3, Cartographic, Math as CMath, Color, Rectangle, JulianDate, NearFarScalar, GeometryInstance, CylinderGeometry, Matrix4, Matrix3, ColorGeometryInstanceAttribute, BoundingSphere, HeadingPitchRange,
} from '@cesium/core';
import {
  CesiumWidget, GeographicTilingScheme, UrlTemplateImageryProvider, ImageryLayer, CesiumTerrainProvider, Cesium3DTileset, Cesium3DTileStyle, Credit, ScreenSpaceEventHandler, ScreenSpaceEventType, sampleTerrainMostDetailed, Ion, VerticalOrigin, HeightReference, BillboardCollection, Primitive, Transforms, PerInstanceColorAppearance, ShadowMode, SunLight, DirectionalLight,
} from '@cesium/engine';

window.CESIUM_BASE_URL = __CESIUM_BASE__;
Ion.defaultAccessToken = '';           // no Cesium ion: every tile comes from swisstopo

const box = document.getElementById('carte');
const T = JSON.parse(document.getElementById('carte-i18n').textContent);
const lang = T.lang;
const status = document.getElementById('carte-etat');
const nf = new Intl.NumberFormat(T.locale, { maximumFractionDigits: 1 });
const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const small = window.innerWidth < 700;
const LAUSANNE = { lon: 6.6323, lat: 46.5197 };
const BOUNDS = { w: 6.42, e: 6.86, s: 46.38, n: 46.66 };      // the camera stays over the Lausanne area
const COL = { good: '#2ca25f', mid: '#f2cf2b', low: '#f28e2b', bad: '#d7301f' };
const colour = (pct) => (pct >= 90 ? COL.good : pct >= 75 ? COL.mid : pct >= 60 ? COL.low : COL.bad);
const columnHeight = (pct) => Math.min(120, 15 + (100 - pct) * 2.6);

const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const fail = () => { status.hidden = false; status.textContent = T.map_nowebgl; };

// ------------------------------------------------------------------ swisstopo data
const SWISS = Rectangle.fromDegrees(5.140242, 45.398181, 11.47757, 48.230651);
const swisstopo = new Credit('© swisstopo', true);
function wmts(layer, format, maximumLevel) {
  // swisstopo's geographic (EPSG:4326) tile pyramid made for 3D viewers.
  return new UrlTemplateImageryProvider({
    url: `https://wmts.geo.admin.ch/1.0.0/${layer}/default/current/4326/{z}/{x}/{y}.${format}`,
    tilingScheme: new GeographicTilingScheme({ numberOfLevelZeroTilesX: 2, numberOfLevelZeroTilesY: 1 }),
    rectangle: SWISS, minimumLevel: 8, maximumLevel, credit: swisstopo,
  });
}
const PHOTO = () => new ImageryLayer(wmts('ch.swisstopo.swissimage-product', 'jpeg', 19));
const PLAN = () => new ImageryLayer(wmts('ch.swisstopo.swisstlm3d-karte-farbe.3d', 'jpeg', 17));

let widget;
try {
  widget = new CesiumWidget(box, {
    baseLayer: PHOTO(),
    terrainProvider: undefined,
    creditContainer: box.querySelector('.map-credits'),
    requestRenderMode: true, maximumRenderTimeChange: Infinity,
    shadows: !small, msaaSamples: small ? 1 : 4,
    useBrowserRecommendedResolution: small,
    showRenderLoopErrors: false,
  });
} catch (e) {
  fail();
  throw e;
}
const scene = widget.scene;
const camera = widget.camera;
const globe = scene.globe;
status.hidden = true;
box.classList.add('is-ready');

globe.baseColor = Color.fromCssColorString('#1b2430');
globe.depthTestAgainstTerrain = true;
globe.enableLighting = true;
globe.dynamicAtmosphereLighting = true;
globe.showGroundAtmosphere = true;
globe.maximumScreenSpaceError = small ? 2 : 1.5;
globe.tileCacheSize = 300;
scene.fog.enabled = true;
scene.fog.density = 0.00012;
scene.highDynamicRange = false;
scene.postProcessStages.fxaa.enabled = small;
if (scene.shadowMap) { scene.shadowMap.softShadows = false; scene.shadowMap.size = 2048; scene.shadowMap.darkness = 0.45; scene.shadowMap.maximumDistance = 3000; }
const ctl = scene.screenSpaceCameraController;
ctl.minimumZoomDistance = 60;
ctl.maximumZoomDistance = 18000;
widget.clock.shouldAnimate = false;

CesiumTerrainProvider.fromUrl('https://3d.geo.admin.ch/ch.swisstopo.terrain.3d/v1/', { requestVertexNormals: true, credit: swisstopo })
  .then((tp) => { widget.terrainProvider = tp; placeColumns(); scene.requestRender(); })
  .catch(() => {});

let buildings;
Cesium3DTileset.fromUrl('https://3d.geo.admin.ch/ch.swisstopo.swissbuildings3d.3d/v1/tileset.json', {
  maximumScreenSpaceError: small ? 16 : 6, shadows: ShadowMode.ENABLED, cacheBytes: 384 * 1024 * 1024,
  dynamicScreenSpaceError: true, foveatedScreenSpaceError: true,
}).then((ts) => {
  buildings = ts;
  ts.credits = [swisstopo];
  scene.primitives.add(ts);
  applyLight();
  if (!pressed('t-buildings')) ts.show = false;
}).catch(() => {});

// ------------------------------------------------------------------ camera
function lookAtLausanne(duration) {
  const target = Cartesian3.fromDegrees(LAUSANNE.lon, LAUSANNE.lat - 0.004, 470);
  camera.flyToBoundingSphere(new BoundingSphere(target, 50), {
    offset: new HeadingPitchRange(CMath.toRadians(-8), CMath.toRadians(-28), small ? 4200 : 3300),
    duration: reduceMotion ? 0 : duration,
  });
}
lookAtLausanne(0);

// Keep the camera over the Lausanne area.
camera.changed.addEventListener(() => {
  const c = Cartographic.fromCartesian(camera.positionWC);
  const lon = CMath.toDegrees(c.longitude), lat = CMath.toDegrees(c.latitude);
  const cl = Math.min(BOUNDS.e, Math.max(BOUNDS.w, lon)), ca = Math.min(BOUNDS.n, Math.max(BOUNDS.s, lat));
  if (cl !== lon || ca !== lat) {
    camera.setView({ destination: Cartesian3.fromDegrees(cl, ca, c.height),
      orientation: { heading: camera.heading, pitch: camera.pitch, roll: 0 } });
  }
});
camera.percentageChanged = 0.05;

// Point on the ground at the centre of the view (falls back to a point ahead of the camera).
function centre() {
  const ray = camera.getPickRay(new Cartesian2(scene.canvas.clientWidth / 2, scene.canvas.clientHeight / 2));
  const hit = ray && globe.pick(ray, scene);
  if (hit) return hit;
  return Cartesian3.add(camera.positionWC, Cartesian3.multiplyByScalar(camera.directionWC, 2000, new Cartesian3()), new Cartesian3());
}
function orbit(dHeading, newPitch, rangeFactor) {
  const target = centre();
  const range = Cartesian3.distance(camera.positionWC, target) * (rangeFactor || 1);
  const pitch = newPitch != null ? newPitch : camera.pitch;
  camera.flyToBoundingSphere(new BoundingSphere(target, 1), {
    offset: new HeadingPitchRange(camera.heading + dHeading, pitch, Math.min(18000, Math.max(80, range))),
    duration: reduceMotion ? 0 : 0.45,
  });
}
function pan(east, north) {
  const h = Cartographic.fromCartesian(camera.positionWC).height;
  const step = Math.max(40, h * 0.25);
  const enu = Transforms.eastNorthUpToFixedFrame(camera.positionWC);
  const m = Matrix4.getMatrix3(enu, new Matrix3());
  const head = camera.heading;
  const dx = east * Math.cos(head) + north * Math.sin(head), dy = -east * Math.sin(head) + north * Math.cos(head);
  const local = new Cartesian3(dx * step, dy * step, 0);
  const world = Matrix3.multiplyByVector(m, local, new Cartesian3());
  camera.position = Cartesian3.add(camera.position, world, new Cartesian3());
  scene.requestRender();
}

// On-map buttons (Cesium has none of its own) and keyboard control of the focused map.
const nav = el('div', 'map-nav');
[['+', T.map_zoom_in, () => orbit(0, null, 0.6)], ['−', T.map_zoom_out, () => orbit(0, null, 1.6)],
 ['⟲', T.map_rotate_left, () => orbit(CMath.toRadians(-30))], ['⟳', T.map_rotate_right, () => orbit(CMath.toRadians(30))],
 ['⌂', T.map_reset, () => lookAtLausanne(1.2)]].forEach(([sym, label, fn]) => {
  const b = el('button', 'map-nav-btn', sym);
  b.type = 'button'; b.setAttribute('aria-label', label); b.title = label;
  b.addEventListener('click', fn);
  nav.appendChild(b);
});
box.appendChild(nav);
box.tabIndex = 0;
box.addEventListener('keydown', (e) => {
  if (e.target !== box) return;
  const k = e.key;
  const act = { ArrowUp: () => pan(0, 1), ArrowDown: () => pan(0, -1), ArrowLeft: () => pan(-1, 0), ArrowRight: () => pan(1, 0),
    '+': () => orbit(0, null, 0.6), '=': () => orbit(0, null, 0.6), '-': () => orbit(0, null, 1.6),
    PageUp: () => orbit(0, Math.max(CMath.toRadians(-89), camera.pitch - 0.15)), PageDown: () => orbit(0, Math.min(CMath.toRadians(-10), camera.pitch + 0.15)),
    q: () => orbit(CMath.toRadians(-20)), e: () => orbit(CMath.toRadians(20)), Escape: () => closeCard() }[k];
  if (act) { e.preventDefault(); act(); }
});

// ------------------------------------------------------------------ light: real sun, or fixed day / night
let lightMode = 'auto';
function zurichDate(hourLocal) {
  const d = new Date();
  const offset = (new Date(d.toLocaleString('en-US', { timeZone: 'Europe/Zurich' })) - new Date(d.toLocaleString('en-US', { timeZone: 'UTC' }))) / 3600000;
  const utc = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), hourLocal - offset, 0, 0);
  return new Date(utc);
}
function sunAltitude(date) {
  const rad = Math.PI / 180, d = date / 86400000 - 0.5 + 2440588 - 2451545, e = rad * 23.4397;
  const M = rad * (357.5291 + 0.98560028 * d);
  const L = M + rad * (1.9148 * Math.sin(M) + 0.02 * Math.sin(2 * M) + 0.0003 * Math.sin(3 * M)) + rad * 102.9372 + Math.PI;
  const dec = Math.asin(Math.sin(e) * Math.sin(L)), ra = Math.atan2(Math.sin(L) * Math.cos(e), Math.cos(L));
  const H = rad * (280.16 + 360.9856235 * d) + rad * LAUSANNE.lon - ra, phi = rad * LAUSANNE.lat;
  return Math.asin(Math.sin(phi) * Math.sin(dec) + Math.cos(phi) * Math.cos(dec) * Math.cos(H)) / rad;
}
// Day: the real sun lights terrain, photos and buildings, with shadows.
// Night: a cool "moonlight" from above keeps the city readable; photos are dimmed, columns glow.
const SUN = new SunLight();
const MOON = new DirectionalLight({ direction: new Cartesian3(0, 0, -1), color: Color.fromCssColorString('#a9bde6'), intensity: 1.15 });
function applyLight() {
  const date = lightMode === 'day' ? zurichDate(14) : lightMode === 'night' ? zurichDate(22) : new Date();
  widget.clock.currentTime = JulianDate.fromDate(date);
  const night = sunAltitude(date) < -4;
  box.classList.toggle('is-night', night);
  if (night) {
    // Light straight down from above the camera's area, in Earth-fixed coordinates.
    const up = Cartesian3.normalize(Cartesian3.fromDegrees(LAUSANNE.lon, LAUSANNE.lat), new Cartesian3());
    MOON.direction = Cartesian3.negate(up, new Cartesian3());
  }
  scene.light = night ? MOON : SUN;
  globe.enableLighting = !night;
  if (scene.skyAtmosphere) { scene.skyAtmosphere.brightnessShift = night ? -0.75 : 0; scene.skyAtmosphere.saturationShift = night ? -0.4 : 0; }
  if (scene.shadowMap) scene.shadowMap.enabled = !small && !night;
  const base = scene.imageryLayers.get(0);
  if (base) { base.brightness = night ? 0.42 : 1.0; base.saturation = night ? 0.45 : 1.0; base.contrast = night ? 1.15 : 1.0; base.gamma = 1.0; }
  if (buildings) buildings.style = new Cesium3DTileStyle({ color: night ? "color('#b8b2a8')" : "color('#f3eee6')" });
  if (stopsPrim) stopsPrim.appearance = new PerInstanceColorAppearance({ closed: true, translucent: false, flat: night });
  scene.requestRender();
}

// ------------------------------------------------------------------ data: columns and pins
const stopsById = {};
let stops = [], disruptions = [], stopsPrim = null, placing = false;
const pins = scene.primitives.add(new BillboardCollection({ scene }));

function pinImage(fill) {
  const c = document.createElement('canvas'), s = 2;
  c.width = 30 * s; c.height = 42 * s;
  const g = c.getContext('2d');
  g.scale(s, s);
  g.beginPath(); g.moveTo(15, 41); g.bezierCurveTo(9, 30, 2, 24, 2, 15); g.arc(15, 15, 13, Math.PI, 0); g.bezierCurveTo(28, 24, 21, 30, 15, 41); g.closePath();
  g.fillStyle = fill; g.fill(); g.lineWidth = 2.5; g.strokeStyle = '#ffffff'; g.stroke();
  g.beginPath(); g.arc(15, 15, 5, 0, 2 * Math.PI); g.fillStyle = '#ffffff'; g.fill();
  return c;
}
const PIN_PLANNED = pinImage('#e39b16'), PIN_UNPLANNED = pinImage('#d6452a');

function drawPins() {
  pins.removeAll();
  disruptions.forEach((p, i) => {
    pins.add({
      position: Cartesian3.fromDegrees(p.lon, p.lat), heightReference: HeightReference.CLAMP_TO_GROUND,
      image: p.planifie ? PIN_PLANNED : PIN_UNPLANNED, width: 30, height: 42, verticalOrigin: VerticalOrigin.BOTTOM,
      disableDepthTestDistance: Number.POSITIVE_INFINITY, scaleByDistance: new NearFarScalar(400, 1.1, 9000, 0.6),
      id: { kind: 'disr', i },
    });
  });
  pins.show = pressed('t-disr');
  scene.requestRender();
}

// Columns stand on the real ground: heights come from swisstopo's terrain.
async function placeColumns() {
  if (!stops.length || placing || !(widget.terrainProvider instanceof CesiumTerrainProvider)) return;
  placing = true;
  const cartos = stops.map((s) => Cartographic.fromDegrees(s.lon, s.lat));
  try { await sampleTerrainMostDetailed(widget.terrainProvider, cartos); } catch (e) { /* keep zero heights */ }
  const instances = stops.map((s, i) => {
    const h = columnHeight(s.pct);
    const ground = cartos[i].height || 0;
    const frame = Transforms.eastNorthUpToFixedFrame(Cartesian3.fromDegrees(s.lon, s.lat, ground));
    return new GeometryInstance({
      geometry: new CylinderGeometry({ length: h, topRadius: 11, bottomRadius: 11, slices: 28 }),
      modelMatrix: Matrix4.multiplyByTranslation(frame, new Cartesian3(0, 0, h / 2 - 1), new Matrix4()),
      id: { kind: 'stop', id: String(s.id) },
      attributes: { color: ColorGeometryInstanceAttribute.fromColor(Color.fromCssColorString(colour(s.pct))) },
    });
  });
  if (stopsPrim) scene.primitives.remove(stopsPrim);
  stopsPrim = scene.primitives.add(new Primitive({
    geometryInstances: instances, shadows: ShadowMode.CAST_ONLY,
    appearance: new PerInstanceColorAppearance({ closed: true, translucent: false, flat: box.classList.contains('is-night') }),
  }));
  stopsPrim.show = pressed('t-stops');
  placing = false;
  scene.requestRender();
}

fetch(box.getAttribute('data-src'), { credentials: 'same-origin' }).then((r) => r.json()).then((d) => {
  stops = d.arrets || [];
  stops.forEach((s) => { stopsById[String(s.id)] = s; });
  disruptions = d.perturbations || [];
  drawPins();
  placeColumns();
}).catch(() => {});

// ------------------------------------------------------------------ info card (DOM, never HTML strings)
const card = el('div', 'map-card');
card.hidden = true;
card.setAttribute('role', 'dialog');
card.setAttribute('aria-modal', 'false');
const cardBody = el('div');
const cardClose = el('button', 'map-card-close', '×');
cardClose.type = 'button';
cardClose.setAttribute('aria-label', T.close);
cardClose.addEventListener('click', () => closeCard());
card.append(cardClose, cardBody);
box.appendChild(card);
let lastFocus = null;
function openCard(nodes, label) {
  cardBody.textContent = '';
  nodes.forEach((n) => cardBody.appendChild(n));
  card.setAttribute('aria-label', label);
  card.hidden = false;
  lastFocus = document.activeElement;
}
function closeCard() {
  if (card.hidden) return;
  card.hidden = true;
  if (lastFocus && lastFocus.focus) lastFocus.focus();
}
function showStop(s) {
  const rows = [[T.col_ontime, nf.format(s.pct) + (lang === 'en' || lang === 'it' ? '%' : ' %')],
    [T.col_delay, s.retard == null ? '–' : nf.format(s.retard) + ' ' + T.min],
    [T.col_measured, nf.format(s.mesures)], [T.col_cancel, nf.format(s.supprimes)], [T.col_lines, (s.lignes || []).slice(0, 8).join(', ')]];
  const nodes = [el('p', 'pp-title', s.nom)];
  rows.forEach(([k, v]) => { const p = el('p', 'pp-row'); p.append(el('span', 'pp-k', k), el('span', 'pp-v', v)); nodes.push(p); });
  openCard(nodes, s.nom);
}
function showDisruption(p) {
  openCard([el('p', 'pp-kind', p.planifie ? T.disr_planned : T.disr_unplanned),
    el('p', 'pp-title', (p.textes && p.textes[lang]) || ''), el('p', 'muted', p.lieu || '')], (p.textes && p.textes[lang]) || '');
}

const handler = new ScreenSpaceEventHandler(scene.canvas);
function pickAt(pos) {
  const picked = scene.pick(pos);
  return picked && picked.id && picked.id.kind ? picked.id : null;
}
handler.setInputAction((e) => {
  const hit = pickAt(e.position);
  if (!hit) return;
  if (hit.kind === 'stop' && stopsById[hit.id]) showStop(stopsById[hit.id]);
  if (hit.kind === 'disr' && disruptions[hit.i]) showDisruption(disruptions[hit.i]);
}, ScreenSpaceEventType.LEFT_CLICK);
let hoverQueued = false, hoverPos = null;
handler.setInputAction((e) => {
  hoverPos = e.endPosition;
  if (hoverQueued || small) return;
  hoverQueued = true;
  requestAnimationFrame(() => { hoverQueued = false; scene.canvas.style.cursor = pickAt(hoverPos) ? 'pointer' : ''; });
}, ScreenSpaceEventType.MOUSE_MOVE);

// ------------------------------------------------------------------ side panel controls
function pressed(id) { const b = document.getElementById(id); return !b || b.getAttribute('aria-pressed') === 'true'; }
function bindToggle(id, fn) {
  const b = document.getElementById(id);
  if (!b) return;
  b.addEventListener('click', () => { const on = b.getAttribute('aria-pressed') !== 'true'; b.setAttribute('aria-pressed', String(on)); fn(on); scene.requestRender(); });
}
bindToggle('t-stops', (on) => { if (stopsPrim) stopsPrim.show = on; });
bindToggle('t-disr', (on) => { pins.show = on; });
bindToggle('t-buildings', (on) => { if (buildings) buildings.show = on; });
bindToggle('t-photo', (on) => {
  scene.imageryLayers.removeAll();
  scene.imageryLayers.add(on ? PHOTO() : PLAN());
  applyLight();
});
bindToggle('t-2d', (on) => orbit(0, on ? CMath.toRadians(-89.9) : CMath.toRadians(-30)));
document.querySelectorAll('[data-light]').forEach((b) => {
  b.addEventListener('click', () => {
    lightMode = b.getAttribute('data-light');
    document.querySelectorAll('[data-light]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    applyLight();
  });
});
document.querySelectorAll('[data-fly]').forEach((b) => {
  b.addEventListener('click', () => {
    const s = stopsById[b.getAttribute('data-fly')];
    if (!s) return;
    box.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'center' });
    const target = Cartesian3.fromDegrees(s.lon, s.lat, (Cartographic.fromCartesian(centre()).height || 450) + 30);
    camera.flyToBoundingSphere(new BoundingSphere(target, 40), {
      offset: new HeadingPitchRange(camera.heading, CMath.toRadians(-32), 520),
      duration: reduceMotion ? 0 : 1.8,
      complete: () => { showStop(s); box.focus(); },
    });
  });
});

applyLight();
setInterval(() => { if (lightMode === 'auto') applyLight(); }, 5 * 60 * 1000);

// ------------------------------------------------------------------ weather (through our Worker, cached)
const WMO = {
  fr: { 0: 'Ciel dégagé', 1: 'Plutôt dégagé', 2: 'Partiellement nuageux', 3: 'Couvert', 45: 'Brouillard', 51: 'Bruine', 61: 'Pluie', 71: 'Neige', 80: 'Averses', 95: 'Orage' },
  de: { 0: 'Klar', 1: 'Überwiegend klar', 2: 'Teilweise bewölkt', 3: 'Bedeckt', 45: 'Nebel', 51: 'Nieselregen', 61: 'Regen', 71: 'Schnee', 80: 'Schauer', 95: 'Gewitter' },
  it: { 0: 'Sereno', 1: 'Prevalentemente sereno', 2: 'Parzialmente nuvoloso', 3: 'Coperto', 45: 'Nebbia', 51: 'Pioviggine', 61: 'Pioggia', 71: 'Neve', 80: 'Rovesci', 95: 'Temporale' },
  en: { 0: 'Clear sky', 1: 'Mainly clear', 2: 'Partly cloudy', 3: 'Overcast', 45: 'Fog', 51: 'Drizzle', 61: 'Rain', 71: 'Snow', 80: 'Showers', 95: 'Thunderstorm' },
}[lang];
const describe = (code) => { for (const k of [95, 80, 71, 61, 51, 45, 3, 2, 1, 0]) if (code >= k) return WMO[k]; return ''; };
fetch('/api/weather', { credentials: 'same-origin' }).then((r) => { if (!r.ok) throw new Error(); return r.json(); }).then((w) => {
  const c = w.current || {}, panel = document.getElementById('meteo');
  panel.textContent = '';
  panel.append(el('p', 'legend-title', T.map_weather), el('p', 'weather-now', nf.format(Math.round(c.temperature_2m)) + ' °C'),
    el('p', null, describe(c.weather_code) + ' · ' + nf.format(Math.round(c.wind_speed_10m)) + ' km/h'));
  // The scene follows the sky: haze in fog, a denser atmosphere under heavy cloud.
  if (c.weather_code >= 45 && c.weather_code < 50) scene.fog.density = 0.0007;
  else if (c.weather_code >= 3) scene.fog.density = 0.00025;
  scene.requestRender();
}).catch(() => {});

window.addEventListener('pagehide', () => { try { widget.destroy(); } catch (e) { /* page is going away */ } });
