// Choosing a location on a map in the contribution and editing forms. Progressive enhancement only: the
// coordinate fields and the type-to-search place fields work the same without it.
// - Coordinates (a place record): a click, a dragged marker or "use the centre of the map" fills latitude and
//   longitude. The contributor still chooses the precision; a click is never presented as an exact, sourced point,
//   and the accuracy of the click at the current zoom is stated.
// - A place field (where an event happened, a birthplace…): the map shows published places with documented
//   coordinates; choosing one fills the field. A click elsewhere lists the nearest published places and offers to
//   propose a new place at that point. Events are located only through place records, never by loose coordinates.
// Everything comes from this server: the vendored map library, the Natural Earth base map, the archive's elevation
// tiles and /map/places.json (published places only). Record text is inserted with textContent only.
(function () {
  'use strict';

  var BM = window.ELFBasemap;                           // static/js/basemap.js (the shared reference map)

  function ready(fn) { if (document.readyState !== 'loading') fn(); else document.addEventListener('DOMContentLoaded', fn); }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function fmt(s, vals) { return s.replace(/\{(\w+)\}/g, function (_, k) { return vals[k]; }); }
  function km(a, b) {                                   // great-circle distance, [lon, lat] pairs
    var R = 6371, r = Math.PI / 180, dLat = (b[1] - a[1]) * r, dLon = (b[0] - a[0]) * r;
    var h = Math.sin(dLat / 2) * Math.sin(dLat / 2) + Math.cos(a[1] * r) * Math.cos(b[1] * r) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return 2 * R * Math.asin(Math.sqrt(h));
  }
  function distance(T, d) { return d < 1 ? fmt(T.metres, { n: Math.max(10, Math.round(d * 100) * 10) }) : fmt(T.km, { n: d < 10 ? d.toFixed(1) : Math.round(d) }); }
  function fire(input) { input.dispatchEvent(new Event('input', { bubbles: true })); input.dispatchEvent(new Event('change', { bubbles: true })); }

  ready(function () {
    var cfg = document.getElementById('locpick-config');
    var boxes = document.querySelectorAll('[data-locpick]');
    if (!cfg || !boxes.length || !window.fetch || !BM) return;
    var T = JSON.parse(cfg.getAttribute('data-i18n'));
    function loadLib() { return BM.load(cfg.getAttribute('data-lib')); }
    function getPlaces() { return BM.places(); }
    function makeMap(container) { return BM.make(container, cfg, { label: T.maplabel, attribution: T.attribution }); }
    // metres covered by a few screen pixels at this zoom: how precise a click can be
    function clickAccuracyKm(map, lat) { return 6 * 78271.517 * Math.cos(lat * Math.PI / 180) / Math.pow(2, map.getZoom()) / 1000; }

    function unavailable(box, msg) { var p = el('p', 'locpick__note', msg); box.querySelector('.locpick__map').replaceWith(p); }

    // ───────────── coordinates of a place record ─────────────
    function pointPicker(box) {
      var lat = document.getElementById(box.getAttribute('data-lat')), lon = document.getElementById(box.getAttribute('data-lon'));
      var prec = document.getElementById(box.getAttribute('data-prec'));
      var self = cfg.getAttribute('data-self') || '';           // the record being corrected is not "already nearby"
      if (!lat || !lon) return;
      box.hidden = false;
      var status = box.querySelector('.locpick__status'), near = box.querySelector('.locpick__near');
      var mapEl = box.querySelector('.locpick__map'), map = null, marker = null;
      function current() {
        var a = parseFloat(lat.value), b = parseFloat(lon.value);
        return isFinite(a) && isFinite(b) && Math.abs(a) <= 90 && Math.abs(b) <= 180 && String(lat.value).trim() && String(lon.value).trim() ? [b, a] : null;
      }
      function describe(ll, how) {
        status.textContent = '';
        if (!ll) { status.textContent = T.nopoint; near.textContent = ''; return; }
        var line = fmt(T.pointat, { lat: ll[1].toFixed(5), lon: ll[0].toFixed(5) });
        if (how === 'map' && map) line += ' ' + fmt(T.accuracy, { d: distance(T, clickAccuracyKm(map, ll[1])) });
        status.appendChild(document.createTextNode(line));
        if (prec && !prec.value) status.appendChild(el('strong', 'locpick__ask', ' ' + T.askprecision));
        nearby(ll);
      }
      function nearby(ll) {
        near.textContent = '';
        getPlaces().then(function (ps) {
          var close = ps.filter(function (p) { return p.id !== self; })
            .map(function (p) { return { p: p, d: km(ll, [p.lon, p.lat]) }; })
            .filter(function (x) { return x.d <= 3; }).sort(function (a, b) { return a.d - b.d; }).slice(0, 3);
          if (!close.length) return;
          near.appendChild(el('p', 'locpick__warn', T.nearexisting));
          var ul = el('ul');
          close.forEach(function (x) {
            var li = el('li'), a = el('a', null, x.p.name); a.href = '/id/' + encodeURIComponent(x.p.id); a.dir = 'auto'; a.target = '_blank'; a.rel = 'noopener';
            li.appendChild(a); li.appendChild(document.createTextNode(' · ' + fmt(T.away, { d: distance(T, x.d) }))); ul.appendChild(li);
          });
          near.appendChild(ul);
        }).catch(function () { /* the check is a help, not a requirement */ });
      }
      function show(ll) {
        if (!map) return;
        if (!ll) { if (marker) { marker.remove(); marker = null; } return; }
        if (!marker) {
          var m = el('div', 'locpick__pin'); m.setAttribute('aria-hidden', 'true');
          marker = new maplibregl.Marker({ element: m, draggable: true, anchor: 'bottom' }).setLngLat(ll).addTo(map);
          m.removeAttribute('aria-label'); m.removeAttribute('role'); m.removeAttribute('tabindex');
          marker.on('dragend', function () { var p = marker.getLngLat(); set([p.lng, p.lat], 'map'); });
        } else marker.setLngLat(ll);
      }
      function set(ll, how) {
        lat.value = ll[1].toFixed(5); lon.value = ll[0].toFixed(5);
        fire(lat); fire(lon);
        show(ll); describe(ll, how);
      }
      [lat, lon].forEach(function (inp) {
        inp.addEventListener('change', function () {
          var ll = current(); show(ll); describe(ll, 'typed');
          if (ll && map && !map.getBounds().contains(ll)) map.jumpTo({ center: ll });
        });
      });
      if (prec) prec.addEventListener('change', function () { describe(current(), 'typed'); });
      box.querySelector('[data-act="centre"]').addEventListener('click', function () {
        if (!map) return; var c = map.getCenter(); set([c.lng, c.lat], 'map');
      });
      box.querySelector('[data-act="clear"]').addEventListener('click', function () {
        lat.value = ''; lon.value = ''; fire(lat); fire(lon); show(null); describe(null);
      });
      describe(current(), 'typed');
      if (!BM.webglOK()) return unavailable(box, T.nowebgl);
      loadLib().then(function () {
        map = makeMap(mapEl);
        var ll = current();
        if (ll && ll[0] > BM.BOUNDS[0][0] && ll[0] < BM.BOUNDS[1][0] && ll[1] > BM.BOUNDS[0][1] && ll[1] < BM.BOUNDS[1][1]) map.jumpTo({ center: ll, zoom: 9 });
        map.on('load', function () { show(current()); box.classList.add('is-live'); });
        map.on('click', function (e) { set([e.lngLat.lng, e.lngLat.lat], 'map'); });
      }).catch(function () { unavailable(box, T.nowebgl); });
    }

    // ───────────── a place field: choose a published place on the map ─────────────
    function placeChooser(box) {
      var input = document.getElementById(box.getAttribute('data-input'));
      if (!input) return;
      box.hidden = false;
      var toggle = box.querySelector('[data-act="toggle"]'), panel = box.querySelector('.locpick__panel');
      var status = box.querySelector('.locpick__status'), near = box.querySelector('.locpick__near');
      var mapEl = box.querySelector('.locpick__map'), map = null, pins = {}, started = false, list = [];
      function chosenId() { var m = /\[([a-z]{3}-[a-z0-9]{8})\]\s*$/.exec(input.value.trim()); return m ? m[1] : ''; }
      function mark() { var id = chosenId(); for (var k in pins) pins[k].classList.toggle('is-chosen', k === id); }
      function choose(p) {
        input.value = p.label; fire(input);
        status.textContent = fmt(T.chosen, { name: p.name }) + (p.precision !== 'exact' ? ' ' + (p.precision === 'approximate' ? T.isapprox : T.isregion) : '');
        near.textContent = ''; mark();
      }
      function pin(p) {
        var b = el('button', 'locpick__place locpick__place--' + p.precision); b.type = 'button';
        var lab = el('span', 'locpick__label', p.name); lab.dir = 'auto'; lab.setAttribute('aria-hidden', 'true'); b.appendChild(lab);
        b.addEventListener('click', function (e) { e.stopPropagation(); choose(p); });
        new maplibregl.Marker({ element: b, anchor: 'center' }).setLngLat([p.lon, p.lat]).addTo(map);
        // set after addTo(), which gives every marker MapLibre's generic "Map marker" label
        b.setAttribute('aria-label', fmt(T.choose, { name: p.name }) + (p.precision !== 'exact' ? ' (' + (p.precision === 'approximate' ? T.approx : T.region) + ')' : ''));
        pins[p.id] = b;
      }
      function clicked(ll) {
        near.textContent = '';
        var close = list.map(function (p) { return { p: p, d: km(ll, [p.lon, p.lat]) }; })
          .filter(function (x) { return x.d <= 50; }).sort(function (a, b) { return a.d - b.d; }).slice(0, 5);
        near.appendChild(el('p', 'small', close.length ? T.nearest : T.nonenear));
        if (close.length) {
          var ul = el('ul', 'locpick__choices');
          close.forEach(function (x) {
            var li = el('li'), b = el('button', 'linkish', x.p.name); b.type = 'button'; b.dir = 'auto';
            b.addEventListener('click', function () { choose(x.p); input.focus(); });
            li.appendChild(b); li.appendChild(document.createTextNode(' · ' + fmt(T.away, { d: distance(T, x.d) }))); ul.appendChild(li);
          });
          near.appendChild(ul);
        }
        var a = el('a', null, T.propose);
        a.href = '/contribute/place?latitude=' + ll[1].toFixed(5) + '&longitude=' + ll[0].toFixed(5);
        a.target = '_blank'; a.rel = 'noopener';
        var p = el('p', 'small'); p.appendChild(a); p.appendChild(document.createTextNode(' ' + T.proposenote)); near.appendChild(p);
      }
      function start() {
        started = true;
        if (!BM.webglOK()) return unavailable(box, T.nowebgl);
        status.textContent = T.loading;
        Promise.all([loadLib(), getPlaces()]).then(function (res) {
          list = res[1];
          map = makeMap(mapEl);
          map.on('load', function () {
            box.classList.add('is-live');
            list.forEach(pin); mark();
            status.textContent = list.length ? fmt(T.placesshown, { n: list.length }) : T.noplaces;
            var cur = list.filter(function (p) { return p.id === chosenId(); })[0];
            if (cur) map.jumpTo({ center: [cur.lon, cur.lat], zoom: 8 });
          });
          map.on('click', function (e) { clicked([e.lngLat.lng, e.lngLat.lat]); });
        }).catch(function () { unavailable(box, T.error); status.textContent = ''; });
      }
      toggle.addEventListener('click', function () {
        var open = panel.hidden;
        panel.hidden = !open; toggle.setAttribute('aria-expanded', String(open));
        if (open && !started) start(); else if (open && map) map.resize();
      });
      input.addEventListener('change', mark);
    }

    boxes.forEach(function (box) {
      if (box.getAttribute('data-locpick') === 'point') pointPicker(box); else placeChooser(box);
    });
  });
})();
