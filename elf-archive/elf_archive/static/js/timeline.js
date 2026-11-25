// The interactive timeline: a horizontal, zoomable view of every public event, linked to the 3D atlas.
// - Events come from /timeline/data.json (the same public records as the list below it). Each event is drawn
//   over exactly the span its record allows (see atlas.date_interval): a day is a point; a month, a year, a decade
//   or a range is a bar, meaning "somewhere within"; approximate dates are dashed; disputed dates are marked.
//   Nothing is placed on an invented date, and undated events are listed, not drawn.
// - Filters, the selected event and the period live in the address (atlas-state.js), shared with the map.
// - Without JavaScript the server-rendered filters and list still work. Text from records uses textContent only.
(function () {
  'use strict';
  var S = window.AtlasState;
  var SVGNS = 'http://www.w3.org/2000/svg';
  var MIN_SPAN = 1 / 12, BUCKET = 46;

  function ready(fn) { if (document.readyState !== 'loading') fn(); else document.addEventListener('DOMContentLoaded', fn); }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function svgEl(tag, attrs) { var e = document.createElementNS(SVGNS, tag); for (var k in attrs) e.setAttribute(k, attrs[k]); return e; }
  function fmt(s, v) { return s.replace(/\{(\w+)\}/g, function (_, k) { return v[k]; }); }
  function getJSON(u) { return fetch(u, { headers: { Accept: 'application/json' } }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }); }
  function shape(cat, size) {
    var s = svgEl('svg', { 'class': 'tl-shape tl-shape--' + cat, viewBox: '0 0 16 16', width: size, height: size, 'aria-hidden': 'true', focusable: 'false' });
    if (cat === 'conflict') s.appendChild(svgEl('rect', { x: 3, y: 3, width: 10, height: 10 }));
    else if (cat === 'political') s.appendChild(svgEl('path', { d: 'M8 2 14 8 8 14 2 8Z' }));
    else if (cat === 'people') s.appendChild(svgEl('circle', { cx: 8, cy: 8, r: 5.2 }));
    else s.appendChild(svgEl('path', { d: 'M8 2.5 14 13.5H2Z' }));
    return s;
  }
  function uncertain(ev) { return ev.precision === 'approximate' || ev.precision === 'decade'; }

  ready(function () {
    var root = document.getElementById('tl-scope'), store = S && S.store;
    if (!root || !store || !window.fetch) return;
    var T = JSON.parse(root.getAttribute('data-i18n'));
    var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var countEl = document.getElementById('tl-count');
    var track = document.getElementById('tl-track'), marks = document.getElementById('tl-marks'), axis = document.getElementById('tl-axis');
    var band = document.getElementById('tl-band'), overview = document.getElementById('tl-overview');
    var summary = document.getElementById('tl-summary'), card = document.getElementById('tl-card');
    var listEl = document.getElementById('tl-list'), serverList = document.getElementById('tl-list-server');

    var events = [], byId = {}, filtered = [], dated = [], undated = [];
    var view = null, domain = null, selected = null, lastTrigger = null, previews = {}, timer, dataReady = false;
    var FILTER_KEYS = ['q', 'type', 'from', 'to', 'region', 'media', 'at', 'person', 'organization'];
    function isShown() { var m = store.get().mode; return m === 'timeline' || m === 'both'; }
    summary.textContent = T.loading;

    // ───────────── filters (shared rules with the map: atlas-state.js) ─────────────
    function current() { return store.get(); }    // the shared exploration state (atlas-state.js)

    function apply(fit) {
      var f = current();
      filtered = events.filter(function (ev) { return S.eventMatches(ev, f); });
      dated = filtered.filter(function (ev) { return ev.t0 !== null; }).sort(function (a, b) { return a.t0 - b.t0 || a.t1 - b.t1; });
      undated = filtered.filter(function (ev) { return ev.t0 === null; });
      domain = dated.length ? padded(dated[0].t0, Math.max.apply(null, dated.map(function (e) { return e.t1; }))) : null;
      var dropped = false;
      if (selected && filtered.indexOf(selected) < 0) {          // say why the card closed, and keep the state honest
        closeCardUI(true); dropped = true;
        store.set({ event: '' }, 'replace');
      }
      if (domain && (fit || !view)) {
        if (f.from || f.to) view = { a: f.from || domain.a, b: (f.to ? f.to + 1 : domain.b) };
        else view = { a: domain.a, b: domain.b };
      }
      renderCount(); renderList(); buildOverview(); render();
      if (dropped) countEl.textContent += ' ' + T.deselected;
    }
    function padded(a, b) { var p = Math.max(0.5, (b - a) * 0.04); return { a: Math.floor(a - p), b: Math.ceil(b + p) }; }

    function renderCount() {
      countEl.textContent = !events.length ? T.noneall : !filtered.length ? T.none :
        (filtered.length === 1 ? T.count1 : fmt(T.count, { n: filtered.length })) + (undated.length ? ' · ' + fmt(T.undated, { n: undated.length }) : '') + '.';
    }

    // ───────────── the horizontal timeline ─────────────
    function width() { return marks.clientWidth || 600; }
    function lanes() { return width() < 640 ? 3 : 5; }
    function x(t) { return (t - view.a) * width() / (view.b - view.a); }

    function label(ev) {
      var cat = T.categories[ev.category] || '';
      return [ev.title, ev.date + (ev.precision_note ? ' (' + ev.precision_note + ')' : ''), ev.type_label || cat,
              ev.date_disputed ? T.disputed : ''].filter(Boolean).join(' — ');
    }

    function render() {
      if (!isShown()) return;                            // hidden in map mode: drawn when shown
      marks.textContent = ''; axis.textContent = '';
      if (!domain || !view) { band.hidden = true; summary.textContent = events.length ? T.none : T.noneall; return; }
      drawAxis();
      var f = current(), W = width();
      if (f.from || f.to) {
        var bx0 = Math.max(0, x(f.from || view.a)), bx1 = Math.min(W, x(f.to ? f.to + 1 : view.b));
        band.hidden = bx1 <= bx0; band.style.left = bx0 + 'px'; band.style.width = (bx1 - bx0) + 'px';
      } else band.hidden = true;
      var visible = dated.filter(function (ev) { return ev.t1 >= view.a && ev.t0 <= view.b; });
      var ends = [], L = lanes(), overflow = {};
      for (var i = 0; i < L; i++) ends.push(-Infinity);
      visible.forEach(function (ev) {
        var left, w;
        if (ev.point) { left = x((ev.t0 + ev.t1) / 2) - 12; w = 24; }            // 24 px: the minimum touch target
        else { left = x(ev.t0); w = Math.max(x(ev.t1) - left, 12); }
        var lane = -1;
        for (var j = 0; j < L; j++) if (ends[j] + 4 <= left) { lane = j; break; }
        if (lane < 0) { var bk = Math.floor((left + w / 2) / BUCKET); (overflow[bk] = overflow[bk] || []).push(ev); return; }
        ends[lane] = left + w;
        marks.appendChild(marker(ev, left, w, lane));
      });
      Object.keys(overflow).forEach(function (bk) {           // too many to show apart: summarised, opened by zooming
        var evs = overflow[bk], b = el('button', 'tl-more', '+' + evs.length); b.type = 'button';
        b.style.left = (bk * BUCKET + BUCKET / 2 - 16) + 'px';
        b.setAttribute('aria-label', fmt(T.more, { n: evs.length }));
        b.addEventListener('click', function () {
          var a = Math.min.apply(null, evs.map(function (e) { return e.t0; })), z = Math.max.apply(null, evs.map(function (e) { return e.t1; }));
          var mid = (a + z) / 2, half = Math.max((z - a) * 0.75, (view.b - view.a) / 6, MIN_SPAN);
          setView(mid - half, mid + half, true);
        });
        marks.appendChild(b);
      });
      var used = ends.filter(function (e) { return e > -Infinity; }).length;      // the track is only as tall as the rows in use
      track.style.height = 'calc(' + (14 + Math.max(2, used) * 30 + 8) + 'px + 2.2rem)';
      var nU = visible.filter(uncertain).length;
      summary.textContent = fmt(visible.length === 1 ? T.inview1 : T.inview, { from: yearLabel(view.a), to: yearLabel(view.b), n: visible.length }) +
        (nU ? ' · ' + fmt(T.uncertainview, { n: nU }) : '');
      updateOverview();
    }

    function marker(ev, left, w, lane) {
      var b = el('button', 'tl-ev tl-ev--' + ev.category + (ev.point ? ' is-point' : ' is-span') + (uncertain(ev) ? ' is-uncertain' : '') +
                           (ev.date_disputed ? ' is-disputed' : '') + (selected === ev ? ' is-selected' : ''));
      b.type = 'button';
      b.style.left = left + 'px'; b.style.width = w + 'px'; b.style.top = (14 + lane * 30) + 'px';
      b.setAttribute('aria-label', label(ev));
      b.setAttribute('data-id', ev.id);
      if (selected === ev) b.setAttribute('aria-pressed', 'true');
      if (!ev.point) { var bar = el('span', 'tl-ev__bar'); bar.setAttribute('aria-hidden', 'true'); b.appendChild(bar); }
      b.appendChild(shape(ev.category, 16));
      b.addEventListener('click', function () { choose(ev, true); });   // focus stays on the (redrawn) marker
      return b;
    }

    function yearLabel(t) {
      var y = Math.floor(t + 1e-6), m = Math.floor((t - y) * 12 + 1e-6);
      return (view.b - view.a) < 3 ? T.months[m] + ' ' + y : String(Math.round(t));
    }
    function drawAxis() {
      var scale = width() / (view.b - view.a), steps = [100, 50, 20, 10, 5, 2, 1, 0.5, 0.25, 1 / 12], step = steps[0];
      for (var i = 0; i < steps.length; i++) { if (steps[i] * scale >= (steps[i] < 1 ? 110 : 64)) step = steps[i]; else break; }
      for (var t = Math.ceil(view.a / step - 1e-9) * step; t <= view.b; t += step) {
        var px = x(t), tick = el('span', 'tl-tick' + (Math.abs(t % 10) < 1e-6 ? ' is-decade' : ''));
        tick.style.left = px + 'px';
        var y = Math.floor(t + 1e-6), mo = Math.round((t - y) * 12);
        tick.textContent = step < 1 ? (mo === 0 ? String(y) : T.months[mo]) : String(Math.round(t));
        axis.appendChild(tick);
      }
    }

    // overview: the whole filtered period, with a window showing what is in view (click to jump there)
    var ovSvg = null, ovWin = null;
    function buildOverview() {
      overview.textContent = ''; ovSvg = null;
      if (!domain) return;
      var years = Math.max(1, Math.ceil(domain.b - domain.a)), counts = [];
      for (var i = 0; i < years; i++) counts.push(0);
      dated.forEach(function (ev) { for (var y = Math.floor(ev.t0); y < Math.ceil(ev.t1); y++) if (y - domain.a >= 0 && y - domain.a < years) counts[y - domain.a]++; });
      var peak = Math.max.apply(null, counts) || 1;
      ovSvg = svgEl('svg', { viewBox: '0 0 ' + years + ' 20', preserveAspectRatio: 'none' });
      counts.forEach(function (c, i) { if (c) ovSvg.appendChild(svgEl('rect', { x: i + 0.15, y: 20 - (c / peak) * 18, width: 0.7, height: (c / peak) * 18, 'class': 'tl-ov-bar' })); });
      ovWin = svgEl('rect', { y: 0, height: 20, 'class': 'tl-ov-win' });
      ovSvg.appendChild(ovWin);
      overview.appendChild(ovSvg);
      var lab = el('div', 'tl-ov-labels'); lab.appendChild(el('span', null, String(domain.a))); lab.appendChild(el('span', null, String(domain.b)));
      overview.appendChild(lab);
    }
    function updateOverview() {
      if (!ovWin || !domain) return;
      var a = Math.max(view.a, domain.a) - domain.a, b = Math.min(view.b, domain.b) - domain.a;
      ovWin.setAttribute('x', a); ovWin.setAttribute('width', Math.max(0.3, b - a));
    }
    overview.addEventListener('click', function (e) {
      if (!domain) return;
      var r = overview.getBoundingClientRect(), t = domain.a + (e.clientX - r.left) / r.width * (domain.b - domain.a), half = (view.b - view.a) / 2;
      setView(t - half, t + half, true);
    });

    // ───────────── moving and zooming ─────────────
    var anim = null;
    function clampView(a, b) {
      var span = Math.max(MIN_SPAN, Math.min(b - a, (domain.b - domain.a) * 1.6 + 10));
      var mid = (a + b) / 2, lo = domain.a - span / 2, hi = domain.b + span / 2;
      mid = Math.max(lo + span / 2, Math.min(hi - span / 2, mid));
      return { a: mid - span / 2, b: mid + span / 2 };
    }
    function setView(a, b, animate) {
      if (!domain) return;
      var target = clampView(a, b);
      if (anim) cancelAnimationFrame(anim);
      if (!animate || reduce) { view = target; render(); return; }
      var from = { a: view.a, b: view.b }, t0 = performance.now();
      (function step(now) {
        var k = Math.min(1, (now - t0) / 260), e = 1 - Math.pow(1 - k, 3);
        view = { a: from.a + (target.a - from.a) * e, b: from.b + (target.b - from.b) * e };
        render();
        if (k < 1) anim = requestAnimationFrame(step); else anim = null;
      })(t0);
    }
    function zoom(factor, at) {
      var c = at === undefined ? (view.a + view.b) / 2 : at;
      setView(c - (c - view.a) * factor, c + (view.b - c) * factor, true);
    }
    function pan(frac) { var d = (view.b - view.a) * frac; setView(view.a + d, view.b + d, true); }

    root.querySelector('.tl-buttons').addEventListener('click', function (e) {
      var b = e.target.closest('[data-act]'); if (!b || !domain) return;
      var act = b.getAttribute('data-act');
      if (act === 'earlier') pan(-0.5);
      else if (act === 'later') pan(0.5);
      else if (act === 'zoom-in') zoom(0.5);
      else if (act === 'zoom-out') zoom(2);
      else if (act === 'all') setView(domain.a, domain.b, true);
      else if (act === 'use-period') {                 // the visible years become the period filter
        store.set({ from: Math.max(1000, Math.ceil(view.a - 1e-6)), to: Math.min(2100, Math.floor(view.b - 1e-6)) }, 'push');
      }
    });

    // drag to move (not over a marker), trackpad / shift-wheel to move, ctrl-wheel or pinch to zoom
    var drag = null;
    track.addEventListener('pointerdown', function (e) {
      if (e.target.closest('button') || !domain) return;
      drag = { x: e.clientX, a: view.a, b: view.b, moved: false };
      track.setPointerCapture(e.pointerId);
    });
    track.addEventListener('pointermove', function (e) {
      if (!drag) return;
      var dx = e.clientX - drag.x; if (Math.abs(dx) > 3) drag.moved = true;
      var dt = -dx * (drag.b - drag.a) / width();
      view = clampView(drag.a + dt, drag.b + dt); render();
    });
    ['pointerup', 'pointercancel'].forEach(function (n) { track.addEventListener(n, function () { drag = null; }); });
    track.addEventListener('wheel', function (e) {
      if (!domain) return;
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        var r = marks.getBoundingClientRect(), at = view.a + (e.clientX - r.left) / r.width * (view.b - view.a), k = Math.exp(e.deltaY * 0.002);
        view = clampView(at - (at - view.a) * k, at + (view.b - at) * k); render();
      } else if (Math.abs(e.deltaX) > Math.abs(e.deltaY) || e.shiftKey) {
        e.preventDefault();
        var d = (e.shiftKey ? e.deltaY : e.deltaX) * (view.b - view.a) / width();
        view = clampView(view.a + d, view.b + d); render();
      }
    }, { passive: false });

    // keyboard: arrows go to the previous / next event (bringing it into view), + and − zoom, Home / End
    track.addEventListener('keydown', function (e) {
      if (!dated.length) return;
      var i = selected ? dated.indexOf(selected) : -1, to = null;
      if (e.key === 'ArrowRight') to = dated[Math.min(dated.length - 1, i + 1)];
      else if (e.key === 'ArrowLeft') to = dated[Math.max(0, i < 0 ? 0 : i - 1)];
      else if (e.key === 'Home') to = dated[0];
      else if (e.key === 'End') to = dated[dated.length - 1];
      else if (e.key === '+' || e.key === '=') { e.preventDefault(); zoom(0.5); return; }
      else if (e.key === '-') { e.preventDefault(); zoom(2); return; }
      else if (e.key === 'Escape' && selected) { e.preventDefault(); closeCard(); return; }
      else return;
      e.preventDefault();
      if (to) choose(to, true);
    });

    function focusMarker(id) {
      var b = marks.querySelector('[data-id="' + CSS.escape(id) + '"]');
      if (b) b.focus({ preventScroll: true });
    }

    // ───────────── selection and the preview card ─────────────
    function bringIntoView(ev) {
      var span = view.b - view.a;
      if (ev.t1 - ev.t0 > span * 0.9) span = (ev.t1 - ev.t0) * 1.4;
      if (ev.t0 < view.a || ev.t1 > view.b || span !== view.b - view.a) { var mid = (ev.t0 + ev.t1) / 2; setView(mid - span / 2, mid + span / 2, true); }
    }
    // a choice goes to the store; the store's event is what the timeline shows (so it, the map and the address agree)
    var focusNext = false;
    function choose(ev, keyboard) { lastTrigger = ev.id; focusNext = !!keyboard; store.set({ event: ev.id, record: '' }, 'push'); }
    function closeCard() { store.set({ event: '' }, 'push'); }
    function select(ev, center, keyboard) {
      selected = ev;
      if (center && ev.t0 !== null && view) bringIntoView(ev);
      render();
      if (keyboard) focusMarker(ev.id);
      showCard(ev);
      listEl.querySelectorAll('.chrono-event.is-selected').forEach(function (n) { n.classList.remove('is-selected'); });
      var li = listEl.querySelector('[data-event="' + CSS.escape(ev.id) + '"]'); if (li) li.classList.add('is-selected');
    }
    function closeCardUI(silent) {
      if (!selected && card.hidden) return;
      card.hidden = true; card.textContent = '';
      var id = selected && selected.id; selected = null;
      listEl.querySelectorAll('.chrono-event.is-selected').forEach(function (n) { n.classList.remove('is-selected'); });
      if (!silent) { render(); if (id && isShown()) focusMarker(id); }
    }
    // to the map: the event, centred on one place if it has exactly one documented location (or on the chosen one)
    function toMap(ev, placeId) {
      var mapped = ev.places.filter(function (p) { return p.mapped; });
      store.set({ mode: store.get().mode === 'both' ? 'both' : 'map', event: ev.id, record: '',
                  place: placeId || (mapped.length === 1 ? mapped[0].id : '') }, 'push');
    }
    function actionButton(cls, text, fn) { var b = el('button', cls, text); b.type = 'button'; b.addEventListener('click', fn); return b; }
    function showCard(ev) {
      card.textContent = ''; card.hidden = false;
      var close = el('button', 'tl-card__close', '×'); close.type = 'button'; close.setAttribute('aria-label', T.close);
      close.addEventListener('click', function () { closeCard(); });
      card.appendChild(close);
      var kick = el('p', 'tl-card__kicker'); kick.appendChild(shape(ev.category, 14));
      kick.appendChild(document.createTextNode(' ' + (ev.type_label || T.categories[ev.category])));
      card.appendChild(kick);
      var h = el('h3', 'tl-card__title'); var a = el('a', null, ev.title); a.href = ev.url; a.dir = 'auto'; h.appendChild(a); card.appendChild(h);
      var when = el('p', 'tl-card__date', ev.date);
      if (ev.precision_note) when.appendChild(el('span', 'tl-card__prec', ' (' + ev.precision_note + ')'));
      card.appendChild(when);
      if (!ev.point && ev.t0 !== null) card.appendChild(el('p', 'tl-card__note', T.within));
      if (ev.date_disputed) { var dp = el('p', 'tl-card__disputed'); var da = el('a', null, T.disputed); da.href = ev.url + '#accounts-h'; dp.appendChild(da); card.appendChild(dp); }
      if (ev.fictional) card.appendChild(el('p', 'badge badge--fictional', T.fictional));
      var media = el('div', 'tl-card__media'); card.appendChild(media);
      if (ev.summary) { var s = el('p', 'tl-card__summary', ev.summary); s.dir = 'auto'; card.appendChild(s); }
      var placesBox = el('div', 'tl-card__section'); placesBox.appendChild(el('h4', 'atlas-label', T.places));
      if (ev.places.length) {
        var ul = el('ul', 'tl-card__places');
        ev.places.forEach(function (p) {
          var li = el('li'), n = el('span', null, p.name); n.dir = 'auto'; li.appendChild(n);
          var notes = [p.region, !p.mapped ? T.unmapped : p.precision === 'approximate' ? T.approx : p.precision === 'region_centroid' ? T.region : '',
                       p.uncertain ? T.uncertainlink : ''].filter(Boolean);
          if (notes.length) li.appendChild(el('span', 'small muted', ' · ' + notes.join(' · ')));
          var links = el('span', 'tl-card__placelinks');
          if (p.mapped) links.appendChild(actionButton('linkish tl-onmap', T.onmap, function () { toMap(ev, p.id); }));
          links.appendChild(actionButton('linkish', T.placeevents, function () { store.label(p.id, p.name); store.set({ at: p.id, event: '' }, 'push'); }));
          li.appendChild(links); ul.appendChild(li);
        });
        placesBox.appendChild(ul);
      } else placesBox.appendChild(el('p', 'small muted', T.noplace));
      card.appendChild(placesBox);
      var people = el('div', 'tl-card__section'); card.appendChild(people);
      var actions = el('p', 'atlas-links');
      var open = el('a', null, T.open); open.href = ev.url; actions.appendChild(open);
      var located = ev.places.some(function (p) { return p.mapped; });
      if (located) actions.appendChild(actionButton('btn btn-small', T.onmap, function () { toMap(ev, ''); }));
      var copy = actionButton('linkish', T.copylink, function () {      // the address holds only public identifiers
        var done = function () { copy.textContent = T.copied; setTimeout(function () { copy.textContent = T.copylink; }, 2500); };
        if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(window.location.href).then(done, function () { copy.textContent = window.location.href; });
        else copy.textContent = window.location.href;
      });
      actions.appendChild(copy);
      card.appendChild(actions);
      if (!located) card.appendChild(el('p', 'small muted', T.nolocation));     // no invented location, no marker
      // people, organizations and an archival image come from the full record preview
      (previews[ev.id] ? Promise.resolve(previews[ev.id]) : getJSON('/map/record/' + encodeURIComponent(ev.id) + '.json')).then(function (r) {
        previews[ev.id] = r;
        if (selected !== ev) return;
        var ph = r.lead;
        if (ph && ph.thumb) {      // an archival image, captioned, opening its full archive record
          var fig = el('figure', 'atlas-lead'), la = el('a'); la.href = ph.url;
          var i = el('img', 'tl-card__img'); i.addEventListener('error', function () { fig.remove(); }); i.src = ph.thumb; i.alt = ph.title; i.loading = 'lazy';
          la.appendChild(i);
          var cap = el('figcaption'), ct = el('span', 'atlas-lead__title', ph.title); ct.dir = 'auto'; cap.appendChild(ct);
          cap.appendChild(el('span', 'atlas-lead__meta', [ph.item_type_label, ph.date || T.nodate].filter(Boolean).join(' · ')));
          var credit = [ph.creator ? fmt(T.by, { name: ph.creator }) : null, ph.rights_holder ? '© ' + ph.rights_holder : null, ph.rights_label].filter(Boolean).join(' · ');
          if (credit) { var cr = el('span', 'atlas-lead__credit', credit); cr.dir = 'auto'; cap.appendChild(cr); }
          la.appendChild(cap); fig.appendChild(la); media.appendChild(fig);
        }
        if (r.photos_total) { var pa = el('a', null, fmt(T.photoslink, { n: r.photos_total })); pa.href = ev.url + '#photos-h'; actions.appendChild(pa); }
        if (r.sources_total) { var sa = el('a', null, fmt(T.sourceslink, { n: r.sources_total })); sa.href = ev.url + '#sources-h'; actions.appendChild(sa); }
        [['people', r.people || []], ['orgs', r.orgs || []]].forEach(function (g) {
          if (!g[1].length) return;
          var box = el('div', 'tl-card__section'); box.appendChild(el('h4', 'atlas-label', T[g[0]]));
          var ul = el('ul', 'atlas-mini');
          g[1].slice(0, 6).forEach(function (p) { var li = el('li'), a2 = el('a', null, p.title); a2.href = p.url; a2.dir = 'auto'; li.appendChild(a2);
            if (p.role) li.appendChild(el('span', 'small', ' · ' + p.role)); ul.appendChild(li); });
          box.appendChild(ul); people.appendChild(box);
        });
      }).catch(function () { /* the card already shows what the timeline knows */ });
    }
    card.addEventListener('keydown', function (e) { if (e.key === 'Escape') { e.preventDefault(); closeCard(); } });

    // ───────────── the chronological list (the alternative to the horizontal view) ─────────────
    function renderList() {
      listEl.textContent = '';
      if (!filtered.length) { listEl.appendChild(el('p', 'atlas-empty', events.length ? T.none : T.noneall)); return; }
      var decade = null, ol = null;
      dated.forEach(function (ev) {
        var d = Math.floor(ev.t0 / 10) * 10;
        if (d !== decade) {
          decade = d;
          var h = el('h2', 'chrono-decade', d + 's'); h.dir = 'ltr'; h.id = 'd' + d + 's'; listEl.appendChild(h);
          ol = el('ol', 'chrono-list'); listEl.appendChild(ol);
        }
        ol.appendChild(listItem(ev));
      });
      if (undated.length) {
        var sec = el('section', 'chrono-undated'); sec.setAttribute('aria-labelledby', 'undated');
        var h2 = el('h2', null, T.undatedh); h2.id = 'undated'; sec.appendChild(h2);
        sec.appendChild(el('p', 'small muted', T.undatednote));
        var ul = el('ul');
        undated.forEach(function (ev) { var li = el('li'), a = el('a', null, ev.title); a.href = ev.url; a.dir = 'auto'; li.appendChild(a); ul.appendChild(li); });
        sec.appendChild(ul); listEl.appendChild(sec);
      }
    }
    function listItem(ev) {
      var li = el('li', 'chrono-event' + (selected === ev ? ' is-selected' : '')); li.setAttribute('data-event', ev.id);
      var when = el('div', 'chrono-when');
      var kind = uncertain(ev) ? 'uncertain' : ev.precision === 'range' ? 'range' : 'precise';
      var mk = el('span', 'chrono-mark chrono-mark--' + kind); mk.setAttribute('aria-hidden', 'true'); when.appendChild(mk);
      var dw = el('span'); dw.appendChild(el('span', 'chrono-when__date', ev.date));
      if (kind !== 'precise' && ev.precision_note) dw.appendChild(el('span', 'chrono-when__note', ev.precision_note));
      if (ev.date_disputed) dw.appendChild(el('span', 'chrono-when__note chrono-when__disputed', T.disputed));
      when.appendChild(dw); li.appendChild(when);
      var body = el('div', 'chrono-body');
      var type = el('div', 'chrono-type'); type.appendChild(shape(ev.category, 12)); type.appendChild(document.createTextNode(' ' + ev.type_label)); body.appendChild(type);
      var h = el('h3'), a = el('a', null, ev.title); a.href = ev.url; a.dir = 'auto'; h.appendChild(a); body.appendChild(h);
      if (ev.summary) { var s = el('p', 'chrono-summary', ev.summary); s.dir = 'auto'; body.appendChild(s); }
      var pl = el('ul', 'chrono-places');
      ev.places.forEach(function (p) {
        var x2 = el('li'); var n = el('span', null, p.name); n.dir = 'auto'; x2.appendChild(n);
        if (p.mapped) x2.appendChild(actionButton('linkish on-map', T.onmap, function () { toMap(ev, p.id); }));
        pl.appendChild(x2);
      });
      var show = el('li'), sb = el('button', 'linkish tl-showin', T.showin); sb.type = 'button';
      sb.addEventListener('click', function () {
        choose(ev, true);
        root.scrollIntoView({ block: 'start', behavior: reduce ? 'auto' : 'smooth' });
      });
      show.appendChild(sb); pl.appendChild(show);
      body.appendChild(pl); li.appendChild(body);
      return li;
    }

    window.addEventListener('resize', function () { clearTimeout(timer); timer = setTimeout(function () { if (isShown()) render(); }, 120); });

    // ───────────── the shared state drives everything ─────────────
    function syncSelection(center) {
      var id = store.get().event, ev = id && byId[id];
      if (ev && filtered.indexOf(ev) >= 0) {
        if (selected !== ev) select(ev, center, focusNext);
        focusNext = false;
      } else if (id && !ev) { store.set({ event: '' }, 'replace'); }          // not a public event: never kept in the state
      else closeCardUI(false);
    }
    store.subscribe(function (s, changed, meta) {
      if (!dataReady) { if (changed.indexOf('mode') >= 0 && isShown()) loadData(); return; }
      var period = changed.indexOf('from') >= 0 || changed.indexOf('to') >= 0;
      if (changed.some(function (k) { return FILTER_KEYS.indexOf(k) >= 0; })) apply(period || meta.reason === 'clear' || meta.reason === 'history');
      if (changed.indexOf('event') >= 0) syncSelection(true);
      if (changed.indexOf('mode') >= 0 && isShown()) { render(); if (selected) bringIntoView(selected); }
    });

    // ───────────── start ─────────────
    // the events are loaded when the timeline is first shown (not while only the map is on screen)
    var loading = false;
    function loadData() {
      if (loading) return;
      loading = true;
      summary.textContent = T.loading;
      getJSON('/timeline/data.json').then(function (data) {
      events = data.events;
      events.forEach(function (ev) { byId[ev.id] = ev; });
      serverList.hidden = true; listEl.hidden = false;
      dataReady = true;
      apply(true);
      var ev = byId[store.get().event];
      if (ev && filtered.indexOf(ev) >= 0 && ev.t0 !== null && !store.get().from && !store.get().to) {
        var span = Math.max(10, (ev.t1 - ev.t0) * 3), mid = (ev.t0 + ev.t1) / 2;
        view = clampView(mid - span / 2, mid + span / 2);
      }
      syncSelection(false);
      }).catch(function (e) { summary.textContent = T.error; if (window.console) console.error(e); });
    }
    if (isShown()) loadData();  });
})();
