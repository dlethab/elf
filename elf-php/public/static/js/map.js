// The historical atlas: a tilted 3D relief map of Eritrea (MapLibre GL JS, WebGL), one view of the explore page.
// - Filters and the selection come from the shared exploration store (atlas-state.js). The map never keeps its own
//   copy: a click asks the store for a change, and the map draws whatever the store holds. The filter bar, the
//   timeline and the address therefore always agree with the markers and the panel.
// - Everything is served from this server: terrain tiles (tools/build_terrain.py), the Natural Earth base map,
//   the archive's places (/map/data.json) and previews (/map/place|record/<id>.json). No third party is contacted
//   unless an administrator configures a street layer.
// - A record appears on the map ONLY through a public place with documented coordinates. Approximate and
//   region-only locations have their own outlines and are never zoomed to as if exact. No routes or connections are drawn.
// - The 3D map starts only when the map is shown. Without WebGL a simplified flat map is drawn; without
//   JavaScript the page lists every place. Record text is inserted with textContent only.
(function () {
  'use strict';

  var ERITREA = [[36.43, 12.36], [43.14, 18.0]];
  var DEM_BOUNDS = [35.0, 11.0, 44.5, 19.5];
  var EXAGGERATION = 1.3, PITCH = 52, BEARING = -12;
  var SVGNS = 'http://www.w3.org/2000/svg';
  var FILTER_KEYS = ['q', 'type', 'from', 'to', 'region', 'media', 'ptype', 'at', 'person', 'organization'];

  function ready(fn) { if (document.readyState !== 'loading') fn(); else document.addEventListener('DOMContentLoaded', fn); }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function svgEl(tag, attrs) { var e = document.createElementNS(SVGNS, tag); for (var k in attrs) e.setAttribute(k, attrs[k]); return e; }
  function fmt(s, vals) { return s.replace(/\{(\w+)\}/g, function (_, k) { return vals[k]; }); }
  function getJSON(url) { return fetch(url, { headers: { Accept: 'application/json' } }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }); }
  function webglOK() {
    try { var c = document.createElement('canvas'); return !!(window.WebGLRenderingContext && (c.getContext('webgl2') || c.getContext('webgl'))); }
    catch (e) { return false; }
  }
  function validLL(p) { return isFinite(p.lat) && isFinite(p.lon) && Math.abs(p.lat) <= 90 && Math.abs(p.lon) <= 180; }
  var prefs = {
    get: function (k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* not remembered */ } }
  };

  // The marker symbol: shape = kind of place, outline = precision (the same drawing as the legend macro in _atlas.html).
  function mark(cat, prec, size) {
    var s = svgEl('svg', { 'class': 'atlas-mark atlas-mark--' + cat + ' atlas-mark--' + prec, viewBox: '0 0 24 24',
                           width: size, height: size, 'aria-hidden': 'true', focusable: 'false' });
    if (prec === 'approximate') s.appendChild(svgEl('circle', { 'class': 'm-halo', cx: 12, cy: 12, r: 10.5 }));
    if (prec === 'region_centroid') s.appendChild(svgEl('circle', { 'class': 'm-zone', cx: 12, cy: 12, r: 11 }));
    if (cat === 'settlement') s.appendChild(svgEl('circle', { 'class': 'm-shape', cx: 12, cy: 12, r: 5.5 }));
    else if (cat === 'area') s.appendChild(svgEl('path', { 'class': 'm-shape', d: 'M12 5.5 18.5 12 12 18.5 5.5 12Z' }));
    else if (cat === 'conflict') s.appendChild(svgEl('rect', { 'class': 'm-shape', x: 6.8, y: 6.8, width: 10.4, height: 10.4 }));
    else s.appendChild(svgEl('path', { 'class': 'm-shape', d: 'M12 5.5 18.5 17.5H5.5Z' }));
    return s;
  }
  var MARK_SIZE = { exact: 22, approximate: 30, region_centroid: 38 };
  // Sources disagree about where the place is: a small split ring beside the marker (the legend macro draws the same).
  function disputeMark() {
    var s = svgEl('svg', { 'class': 'atlas-disputed', viewBox: '0 0 12 12', width: 12, height: 12, 'aria-hidden': 'true', focusable: 'false' });
    s.appendChild(svgEl('path', { d: 'M6 1.5A4.5 4.5 0 0 0 6 10.5' }));
    s.appendChild(svgEl('path', { d: 'M7.5 1.8A4.5 4.5 0 0 1 7.5 10.2' }));
    return s;
  }

  ready(function () {
    var root = document.getElementById('atlas');
    var S = window.AtlasState, store = S && S.store;
    if (!root || !store || !window.fetch) return;
    var T = JSON.parse(root.getAttribute('data-i18n'));
    var attr = function (n) { return JSON.parse(root.getAttribute(n) || 'null'); };
    var tile = attr('data-tile') || '', tileAttribution = attr('data-tile-attribution') || '';
    var rtl = document.documentElement.dir === 'rtl';
    var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var narrow = window.matchMedia ? window.matchMedia('(max-width: 61.99rem)') : { matches: false };
    var css = window.getComputedStyle(document.body);
    var C = function (n) { return css.getPropertyValue('--atlas-' + n).trim(); };

    var view = document.getElementById('atlas-view'), fallback = document.getElementById('atlas-fallback');
    var toast = document.getElementById('atlas-toast'), statusEl = document.getElementById('map-status');
    var resultsEl = document.getElementById('atlas-results'), browse = document.getElementById('atlas-browse');
    var found = document.getElementById('atlas-found'), foundList = document.getElementById('atlas-found-list');
    var detail = document.getElementById('atlas-detail'), controls = document.getElementById('atlas-controls');
    var say = function (t) { statusEl.textContent = t; };
    var note = function (t) { toast.textContent = t; toast.hidden = !t; };

    var places = [], byId = {}, shown = [], selected = null, related = null, recordCtx = null, panelKey = '';
    var map = null, mapReady = false, mapStarted = false, flat = null, saved = null, lastTrigger = null;
    var lowEnd = (navigator.deviceMemory && navigator.deviceMemory <= 2) || (navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 2);
    var pref = prefs.get('elf-atlas-3d'), is3d = pref ? pref !== '0' : !lowEnd;     // modest devices start flat
    var terrainFailed = false, demErrors = 0;
    var markers = {}, onScreen = {}, regionMarkers = [], townMarkers = [];
    var previews = {}, records = {}, timer, searchTimer, searchSeq = 0, dataReady = false;

    fallback.querySelector('span:last-child').textContent = T.loading;
    function visible() { var m = store.get().mode; return m === 'map' || m === 'both'; }

    // ───────────── filters: the shared state, applied to places ─────────────
    function current() {
      var s = store.get();
      return { q: s.q, ptype: s.ptype, type: s.type, from: s.from, to: s.to, person: s.person, org: s.organization,
               media: s.media, region: s.region, at: s.at };
    }
    function matches(p, f) {
      if (f.at && p.id !== f.at) return false;
      if (f.q && (S.norm(p.name) + ' ' + p.names).indexOf(S.norm(f.q)) < 0) return false;
      if (f.ptype) { if (f.ptype.indexOf('cat:') === 0 ? p.category !== f.ptype.slice(4) : p.type !== f.ptype) return false; }
      if (f.person && (p.persons || []).indexOf(f.person) < 0) return false;
      if (f.org && (p.orgs || []).indexOf(f.org) < 0) return false;
      if (f.media && !p.items) return false;
      if (f.region && p.region !== f.region) return false;
      var evs = p.events;
      if (f.type) evs = evs.filter(function (e) { return e.type === f.type; });
      if (f.from || f.to) evs = evs.filter(function (e) { return S.inPeriod(e, f); });     // the timeline's rule
      if ((f.type || f.from || f.to) && !evs.length) return false;
      return true;
    }
    function apply(fit) {
      var f = current();
      shown = places.filter(function (p) { return matches(p, f); });
      say(!places.length ? T.nomapped : shown.length ? fmt(T.shown, { n: shown.length, total: places.length }) : T.none);
      renderList(); ribbon.sync(f);
      redraw();
      if (fit) fitShown();
    }
    // The map shows the filtered places plus, always, the places of the record being viewed and the selected place.
    var layerOn = { evplaces: true, otherplaces: true };          // the archive-place layers (the layer menu)
    function onMap() {
      var out = shown.filter(function (p) { return p.events.length ? layerOn.evplaces : layerOn.otherplaces; });
      (related || []).concat(selected ? [selected.id] : []).forEach(function (id) { var p = byId[id]; if (p && out.indexOf(p) < 0) out.push(p); });
      return out;
    }
    function redraw() {
      if (mapReady) { map.getSource('places').setData(geojson(onMap())); clearMarkers(); }
      if (flat) flat.draw();
    }

    // ───────────── selection: always through the store ─────────────
    function choosePlace(p, b) {
      lastTrigger = b || null;
      var s = store.get(), keep = recordCtx && related && related.indexOf(p.id) >= 0;    // stay "inside" the record being viewed
      store.set({ place: p.id, event: keep ? s.event : '', record: keep ? s.record : '' }, 'push');
    }
    function chooseRecord(kind, id, b) {
      lastTrigger = b || null;
      if (kind === 'place' && byId[id]) return choosePlace(byId[id], b);
      store.set(kind === 'event' ? { event: id, record: '', place: '' } : { record: id, event: '', place: '' }, 'push');
    }
    function closePanel() { store.set({ place: '', event: '', record: '' }, 'push'); }
    function exploreInTimeline(p) {
      store.label(p.id, p.name);
      store.set({ at: p.id, mode: store.get().mode === 'both' ? 'both' : 'timeline', event: '' }, 'push');
    }

    // what the store says is selected → what the panel and the markers show
    function syncSelection() {
      if (!dataReady) return;
      var s = store.get(), recId = s.event || s.record;
      if (s.place) {
        var p = byId[s.place];
        if (!p) { note(T.gone); store.set({ place: '' }, 'replace'); return; }     // public, but not on the map (no coordinates)
        if (recId) loadRecord(recId).then(function (r) { if (store.get().place === p.id) { setRecordCtx(r); openPlace(p, r); } }, function () { openPlace(p, null); });
        else { setRecordCtx(null); openPlace(p, null); }
      } else if (recId) openRecord(recId);
      else closePanelUI();
    }
    function setRecordCtx(r) {
      recordCtx = r;
      related = r ? r.places.filter(function (x) { return byId[x.id]; }).map(function (x) { return x.id; }) : null;
    }
    function loadRecord(id) {
      if (records[id]) return Promise.resolve(records[id]);
      return getJSON('/map/record/' + encodeURIComponent(id) + '.json').then(function (r) { records[id] = r; return r; });
    }

    // ───────────── lists: places on the map, and other records found by the search ─────────────
    function renderList() {
      resultsEl.textContent = '';
      if (!shown.length) { resultsEl.appendChild(el('li', 'atlas-empty', places.length ? T.none : T.nomapped)); return; }
      shown.slice().sort(function (a, b) { return a.name.localeCompare(b.name); }).forEach(function (p) {
        var li = el('li'), b = el('button', 'atlas-result');
        b.type = 'button'; b.setAttribute('data-id', p.id);
        if (selected && selected.id === p.id) b.setAttribute('aria-current', 'true');
        b.appendChild(mark(p.category, p.precision, 18));
        var txt = el('span');
        var name = el('span', 'atlas-result__name', p.name); name.dir = 'auto'; txt.appendChild(name);
        txt.appendChild(el('span', 'atlas-result__meta', [p.type_label, p.region, p.precision_label, p.disputed ? T.disputedshort : ''].filter(Boolean).join(' · ')));
        b.appendChild(txt);
        b.addEventListener('click', function () { choosePlace(p, b); });
        li.appendChild(b); resultsEl.appendChild(li);
      });
    }

    function runSearch() {
      var q = store.get().q, seq = ++searchSeq;
      clearTimeout(searchTimer);
      if (!q || q.length < 2) { found.hidden = true; return; }
      searchTimer = setTimeout(function () {
        found.hidden = false; foundList.textContent = ''; foundList.appendChild(el('li', 'atlas-empty', T.searching));
        getJSON('/map/search.json?q=' + encodeURIComponent(q)).then(function (data) {
          if (seq !== searchSeq) return;
          foundList.textContent = '';
          var others = data.results.filter(function (r) { return !(r.kind === 'place' && byId[r.id] && shown.indexOf(byId[r.id]) >= 0); });
          if (!others.length) { foundList.appendChild(el('li', 'atlas-empty', T.nofound)); return; }
          others.forEach(function (r) {
            var li = el('li'), b = el('button', 'atlas-result atlas-result--record'); b.type = 'button';
            var txt = el('span');
            txt.appendChild(el('span', 'atlas-result__kind', r.kind_label));
            var n = el('span', 'atlas-result__name', r.title); n.dir = 'auto'; txt.appendChild(n);
            var meta = [r.context, r.matched_name].filter(Boolean).join(' · ');
            if (meta) txt.appendChild(el('span', 'atlas-result__meta', meta));
            b.appendChild(txt);
            b.addEventListener('click', function () { chooseRecord(r.kind, r.id, b); });
            li.appendChild(b); foundList.appendChild(li);
          });
        }).catch(function () { if (seq === searchSeq) found.hidden = true; });
      }, 260);
    }

    // ───────────── the panel (side panel on desktop, bottom sheet on phones) ─────────────
    function openPanel(key, nodes, heading) {
      if (detail.hidden) saved = cameraNow();                // closing the panel returns to this view
      panelKey = key;
      detail.textContent = '';
      nodes.forEach(function (n) { if (n) detail.appendChild(n); });
      detail.hidden = false;
      browse.hidden = !narrow.matches;                       // on phones the list stays in place under the sheet
      if (heading && visible()) heading.focus({ preventScroll: true });
      if (visible() && narrow.matches && (view.getBoundingClientRect().top < 0 || view.getBoundingClientRect().top > 80)) {
        view.scrollIntoView({ block: 'start', behavior: reduce ? 'auto' : 'smooth' });   // the map above, the sheet below
      }
    }
    // on phones, centre places in the part of the map the sheet leaves visible
    function sheetPadding() { return narrow.matches && !detail.hidden ? { top: 0, bottom: Math.round(detail.offsetHeight), left: 0, right: 0 } : { top: 0, bottom: 0, left: 0, right: 0 }; }
    function closePanelUI() {
      if (detail.hidden && !selected && !related) return;
      detail.hidden = true; browse.hidden = false; panelKey = '';
      var extra = !!related || (selected && shown.indexOf(selected) < 0);
      selected = null; recordCtx = null; related = null;
      renderList(); if (extra) redraw(); else refreshMarkers();
      if (saved && mapReady) map.easeTo(Object.assign({}, saved, { padding: sheetPadding(), duration: reduce ? 0 : 600 }));
      saved = null;
      if (lastTrigger && !document.body.contains(lastTrigger) && lastTrigger.getAttribute('data-id')) {   // the list was redrawn
        lastTrigger = resultsEl.querySelector('[data-id="' + CSS.escape(lastTrigger.getAttribute('data-id')) + '"]');
      }
      if (lastTrigger && document.body.contains(lastTrigger) && visible()) lastTrigger.focus({ preventScroll: true });
    }
    detail.addEventListener('keydown', function (e) { if (e.key === 'Escape') { e.preventDefault(); closePanel(); } });

    function backButton(label, fn) {
      var b = el('button', 'atlas-back', (rtl ? '→ ' : '← ') + label); b.type = 'button';
      b.addEventListener('click', fn); return b;
    }
    function heading(text) { var h = el('h2', null, text); h.dir = 'auto'; h.tabIndex = -1; return h; }
    function section(title, nodes) {
      var s = el('div', 'atlas-section'); s.appendChild(el('h3', 'atlas-label', title));
      nodes.forEach(function (n) { s.appendChild(n); }); return s;
    }
    function linkList(items, withRole) {
      var ul = el('ul', 'atlas-mini');
      items.forEach(function (it) {
        var li = el('li'), a = el('a', null, it.title); a.href = it.url; a.dir = 'auto'; li.appendChild(a);
        if (withRole && it.role) li.appendChild(el('span', 'small', ' · ' + it.role));
        ul.appendChild(li);
      });
      return ul;
    }
    // an image that cannot be shown (removed, or its rights changed since the page loaded) simply disappears
    function dropOnError(i) { i.addEventListener('error', function () { var li = i.closest('li'); (li && li.parentNode && li.parentNode.classList.contains('atlas-photos') ? li : i).remove(); }); return i; }
    function thumbImg(src) { var i = el('img', 'atlas-thumb'); i.src = src; i.alt = ''; i.loading = 'lazy'; i.decoding = 'async'; return dropOnError(i); }
    // An archival image with its caption: what it is, when it was made, who made it and its rights. The whole figure
    // opens the full archive record (description, provenance, rights, related records, sources).
    function leadFigure(ph) {
      if (!ph || !ph.thumb) return null;
      var fig = el('figure', 'atlas-lead'), a = el('a'); a.href = ph.url;
      var i = el('img'); i.src = ph.thumb; i.alt = ph.title; i.loading = 'lazy'; i.decoding = 'async';
      i.addEventListener('error', function () { fig.remove(); });
      a.appendChild(i);
      var cap = el('figcaption'), t = el('span', 'atlas-lead__title', ph.title); t.dir = 'auto'; cap.appendChild(t);
      cap.appendChild(el('span', 'atlas-lead__meta', [ph.item_type_label, ph.date || T.nodate].filter(Boolean).join(' · ')));
      var credit = [ph.creator ? fmt(T.by, { name: ph.creator }) : null, ph.rights_holder ? '© ' + ph.rights_holder : null, ph.rights_label].filter(Boolean).join(' · ');
      if (credit) { var c = el('span', 'atlas-lead__credit', credit); c.dir = 'auto'; cap.appendChild(c); }
      cap.appendChild(el('span', 'atlas-lead__open', T.openitem));
      a.appendChild(cap); fig.appendChild(a);
      return fig;
    }
    // Copy the address of this public view (the address holds only public identifiers and filters).
    function copyLink() {
      var b = el('button', 'linkish', T.copylink); b.type = 'button';
      b.addEventListener('click', function () {
        var done = function () { say(T.copied); b.textContent = T.copied; setTimeout(function () { b.textContent = T.copylink; }, 2500); };
        if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(window.location.href).then(done, function () { note(window.location.href); });
        else note(window.location.href);
      });
      return b;
    }
    function shortcut(label, href) { var a = el('a', null, label); a.href = href; return a; }
    function disputeBox(list) {
      var box = el('div', 'atlas-dispute');
      box.appendChild(el('p', 'atlas-dispute__h', T.disputedloc));
      list.forEach(function (d) {
        var p = el('p', 'small'); p.dir = 'auto';
        p.appendChild(el('strong', null, d.topic + ': ')); p.appendChild(document.createTextNode(d.text + (d.by ? ' (' + d.by + ')' : '')));
        box.appendChild(p);
      });
      return box;
    }

    function openPlace(p, fromRecord) {
      var key = 'place:' + p.id + ':' + (fromRecord ? fromRecord.id : '');
      selected = p;
      if (key === panelKey) { refreshMarkers(); moveTo(p); return; }
      var back = fromRecord ? backButton(fmt(T.backto, { title: fromRecord.title }), function () { store.set({ place: '' }, 'push'); })
                            : backButton(narrow.matches ? T.close : T.back, closePanel);
      var h = heading(p.name);
      var cert = el('div', 'atlas-certainty'), line = el('p');
      line.appendChild(mark(p.category, p.precision, 18)); line.appendChild(document.createTextNode(' '));
      line.appendChild(el('strong', null, p.precision === 'exact' ? T.exact : p.precision === 'region_centroid' ? T.centroid : T.approx));
      cert.appendChild(line);
      if (p.note) { var n = el('p', null, p.note); n.dir = 'auto'; cert.appendChild(n); }
      var outside = !matches(p, current()) ? el('p', 'atlas-notice', T.outside) : null;
      var body = el('div'); body.appendChild(el('p', 'atlas-loading-line', T.loadingrecord));
      openPanel(key, [back, el('span', 'atlas-kicker', p.type_label), h,
                      el('div', 'atlas-detail__meta', [p.region, p.precision_label].filter(Boolean).join(' · ')),
                      p.fictional ? el('p', 'badge badge--fictional', T.fictional) : null, outside, cert, body], h);
      redraw(); renderList();
      moveTo(p);
      (previews[p.id] ? Promise.resolve(previews[p.id]) : getJSON('/map/place/' + encodeURIComponent(p.id) + '.json'))
        .then(function (d) { previews[p.id] = d; if (selected === p) fillPlace(body, p, d); })
        .catch(function () { body.textContent = ''; body.appendChild(placeLinks(p)); });
    }

    function fillPlace(body, p, d) {
      body.textContent = '';
      var lead = leadFigure(d.lead); if (lead) body.appendChild(lead);
      if (d.location_disputes.length) body.appendChild(disputeBox(d.location_disputes));
      if (d.summary) { var s = el('p', 'atlas-summary', d.summary); s.dir = 'auto'; body.appendChild(section(T.summary, [s])); }
      var names = d.names.map(function (n) { return n.name; });
      if (d.original_name && names.indexOf(d.original_name) < 0) names.unshift(d.original_name);
      if (names.length) { var nm = el('p', null, names.join(' · ')); nm.dir = 'auto'; body.appendChild(section(T.names, [nm])); }
      if (d.valid) body.appendChild(section(T.valid, [el('p', null, d.valid)]));
      if (d.events.length) {
        var ul = el('ul', 'atlas-events');
        d.events.slice(0, 8).forEach(function (ev) {
          var li = el('li', (ev.precision === 'approximate' || ev.precision === 'decade' || ev.uncertain_place) ? 'is-uncertain' : null);
          li.appendChild(el('span', 'atlas-events__date', ev.date));
          var a = el('a', null, ev.title); a.href = ev.url; a.dir = 'auto'; li.appendChild(a);
          if (ev.uncertain_place) li.appendChild(el('span', 'small muted', ' (' + T.uncertainplace + ')'));
          ul.appendChild(li);
        });
        var nodes = [ul];
        if (d.events.length > 8) {
          var more = el('button', 'linkish small', fmt(T.more, { n: d.events.length - 8 })); more.type = 'button';
          more.addEventListener('click', function () { exploreInTimeline(p); }); nodes.push(more);
        }
        body.appendChild(section(T.events, nodes));
      } else body.appendChild(section(T.events, [el('p', 'atlas-empty', T.noevents)]));
      if (d.people.length) body.appendChild(section(T.people, [linkList(d.people, true)]));
      if (d.orgs.length) body.appendChild(section(T.orgs, [linkList(d.orgs)]));
      if (d.families.length) {
        body.appendChild(section(T.families, [linkList(d.families.map(function (f) {
          return { title: f.title, url: f.url, role: fmt(f.n === 1 ? T.familymember1 : T.familymembers, { n: f.n }) }; }), true)]));
      }
      if (d.collections.length) body.appendChild(section(T.collections, [linkList(d.collections)]));
      if (d.photos.length > (d.lead ? 1 : 0)) {
        var grid = el('ul', 'atlas-photos');
        d.photos.filter(function (ph) { return ph !== d.lead && !(d.lead && ph.url === d.lead.url); }).forEach(function (ph) {
          var li = el('li'), a = el('a'); a.href = ph.url; a.title = ph.title;
          if (ph.thumb) { var i = dropOnError(el('img')); i.src = ph.thumb; i.alt = ph.title; i.loading = 'lazy'; a.appendChild(i); } else a.textContent = ph.title;
          li.appendChild(a); grid.appendChild(li);
        });
        body.appendChild(section(T.photos, [grid]));
      }
      var src = d.location_sources.length ? linkList(d.location_sources.map(function (s) {
        return { title: s.title + (s.locator ? ', ' + s.locator : ''), url: s.url }; })) : el('p', 'small muted', T.nolocsource);
      body.appendChild(section(T.locsources, [src]));
      body.appendChild(placeLinks(p, d));
    }
    function placeLinks(p, d) {
      var links = el('p', 'atlas-links');
      if (p.events.length) {          // explicit links only: the timeline then shows events documented AT this place
        var tl = el('button', 'btn btn-small', T.timeline); tl.type = 'button';
        tl.addEventListener('click', function () { exploreInTimeline(p); }); links.appendChild(tl);
      }
      links.appendChild(shortcut(T.history, p.url));
      if (d && d.photos.length) links.appendChild(shortcut(fmt(T.photoslink, { n: d.photos.length }), p.url + '#photos-h'));
      if (d && d.sources_total) links.appendChild(shortcut(fmt(T.sourceslink, { n: d.sources_total }), p.url + '#sources-h'));
      links.appendChild(copyLink());
      return links;
    }

    // A person, event, organization or archive record: preview, and its places on the map (the user chooses).
    function openRecord(id) {
      var key = 'record:' + id;
      if (key === panelKey) return;
      var body = el('div'); body.appendChild(el('p', 'atlas-loading-line', T.loadingrecord));
      var h = heading('…');
      openPanel(key, [backButton(narrow.matches ? T.close : T.back, closePanel), h, body], h);
      loadRecord(id).then(function (r) {
        if (panelKey !== key || !detail.contains(h)) return;      // a newer panel has replaced this one
        setRecordCtx(r); selected = null;
        h.textContent = r.title;
        detail.insertBefore(el('span', 'atlas-kicker', [r.kind_label, r.type_label].filter(Boolean).join(' · ')), h);
        body.textContent = '';
        if (r.date) body.appendChild(el('p', 'atlas-detail__date', r.date + (r.precision_note ? ' (' + r.precision_note + ')' : '')));
        if (r.fictional) body.appendChild(el('p', 'badge badge--fictional', T.fictional));
        if (r.thumb) body.appendChild(thumbImg(r.thumb));
        var lead = leadFigure(r.lead); if (lead) body.appendChild(lead);
        if (r.summary) { var s = el('p', 'atlas-summary', r.summary); s.dir = 'auto'; body.appendChild(s); }
        var mapped = r.places.filter(function (x) { return byId[x.id]; });
        var nodes = [];
        if (mapped.length) {
          if (mapped.length > 1) nodes.push(el('p', 'small', T.choose));
          var ul = el('ul', 'atlas-placepick');
          mapped.forEach(function (x) {
            var p = byId[x.id], li = el('li'), b = el('button', 'atlas-result'); b.type = 'button';
            b.appendChild(mark(p.category, p.precision, 18));
            var t = el('span'), n = el('span', 'atlas-result__name', p.name); n.dir = 'auto'; t.appendChild(n);
            t.appendChild(el('span', 'atlas-result__meta', [p.precision_label, x.uncertain ? T.uncertain : ''].filter(Boolean).join(' · ')));
            b.appendChild(t);
            b.addEventListener('click', function () { choosePlace(p, b); });
            li.appendChild(b); ul.appendChild(li);
          });
          nodes.push(ul);
        } else nodes.push(el('p', 'small muted', T.noplace));          // no invented location: nothing is placed
        if (r.unmapped) nodes.push(el('p', 'small muted', fmt(T.unmapped, { n: r.unmapped })));
        body.appendChild(section(T.onmap, nodes));
        if (r.people && r.people.length) body.appendChild(section(T.people, [linkList(r.people, true)]));
        if (r.orgs && r.orgs.length) body.appendChild(section(T.orgs, [linkList(r.orgs)]));
        var links = el('p', 'atlas-links');
        if (r.kind === 'event') {
          var tb = el('button', 'btn btn-small', T.intimeline); tb.type = 'button';
          tb.addEventListener('click', function () { store.set({ mode: store.get().mode === 'both' ? 'both' : 'timeline' }, 'push'); });
          links.appendChild(tb);
        }
        var a = el('a', null, T.openrecord); a.href = r.url; links.appendChild(a);
        if (r.photos_total) links.appendChild(shortcut(fmt(T.photoslink, { n: r.photos_total }), r.url + '#photos-h'));
        if (r.sources_total) links.appendChild(shortcut(fmt(T.sourceslink, { n: r.sources_total }), r.url + '#sources-h'));
        links.appendChild(copyLink());
        body.appendChild(links);
        redraw();
        if (mapped.length) fitPlaces(mapped.map(function (x) { return byId[x.id]; }));
      }).catch(function (e) {
        if (panelKey !== key || !detail.contains(h)) return;
        if (e && String(e.message) === '404') {               // not public (any more): say so, and drop it from the state
          note(T.gone); panelKey = '';
          store.set({ event: '', record: '' }, 'replace');
        } else { body.textContent = ''; body.appendChild(el('p', 'atlas-empty', T.error)); if (window.console) console.error(e); }
      });
    }

    // ───────────── period ribbon: when the events at mapped places happened ─────────────
    var ribbon = (function () {
      var body = document.getElementById('ribbon-body'), rangeEl = document.getElementById('ribbon-range');
      var lo = 0, hi = 0, groups = [], fromIn, toIn, built = false, dragging = false;
      function build() {
        body.textContent = '';
        var seen = {}, spans = [];
        places.forEach(function (p) { p.events.forEach(function (ev) {
          if (seen[ev.id] || ev.from === null) return; seen[ev.id] = 1;
          var kind = ev.precision === 'approximate' || ev.precision === 'decade' ? 'uncertain' : ev.precision === 'range' ? 'range' : 'precise';
          spans.push([ev.from, Math.max(ev.from, ev.to), kind]);
        }); });
        if (!spans.length) { body.appendChild(el('p', 'atlas-ribbon__empty', T.ribbonempty)); return; }
        lo = Math.floor(Math.min.apply(null, spans.map(function (s) { return s[0]; })) / 10) * 10;
        hi = Math.floor(Math.max.apply(null, spans.map(function (s) { return s[1]; })) / 10) * 10 + 9;
        var years = hi - lo + 1, counts = [];
        for (var i = 0; i < years; i++) counts.push({ precise: 0, range: 0, uncertain: 0 });
        spans.forEach(function (s) { for (var y = s[0]; y <= s[1]; y++) counts[y - lo][s[2]]++; });
        var peak = Math.max.apply(null, counts.map(function (c) { return c.precise + c.range + c.uncertain; })) || 1;
        body.appendChild(el('p', 'sr-only', fmt(T.ribbonlabel, { n: spans.length, from: lo, to: hi })));
        var track = el('div', 'atlas-ribbon__track');
        var svg = svgEl('svg', { viewBox: '0 0 ' + years * 10 + ' 40', preserveAspectRatio: 'none', 'aria-hidden': 'true', focusable: 'false' });
        var defs = svgEl('defs', {}), pat = svgEl('pattern', { id: 'atlas-hatch-map', width: 4, height: 4, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' });
        pat.appendChild(svgEl('line', { x1: 0, y1: 0, x2: 0, y2: 4, 'class': 'hatch-line' })); defs.appendChild(pat); svg.appendChild(defs);
        svg.appendChild(svgEl('rect', { x: 0, y: 39, width: years * 10, height: 1, 'class': 'bar-base' }));
        groups = counts.map(function (c, i) {
          var g = svgEl('g', {}), y = 39;
          ['precise', 'range', 'uncertain'].forEach(function (k) {
            if (!c[k]) return;
            var hgt = Math.max(2, (c[k] / peak) * 36); y -= hgt;
            var r = svgEl('rect', { x: i * 10 + 1.5, y: y, width: 7, height: hgt, 'class': 'bar-' + k });
            if (k === 'uncertain') r.setAttribute('fill', 'url(#atlas-hatch-map)');
            g.appendChild(r);
          });
          svg.appendChild(g); return g;
        });
        track.appendChild(svg);
        var sliders = el('div', 'atlas-ribbon__sliders');
        fromIn = slider(T.fromyear, lo); toIn = slider(T.toyear, hi);
        sliders.appendChild(fromIn); sliders.appendChild(toIn); track.appendChild(sliders);
        body.appendChild(track);
        var axis = el('div', 'atlas-ribbon__axis'), step = Math.max(10, Math.ceil(years / 60) * 10);
        for (var d = lo; d <= hi + 1; d += step) axis.appendChild(el('span', null, String(Math.min(d, hi))));
        body.appendChild(axis);
        var key = el('ul', 'atlas-ribbon__key');
        [['precise', 'swatchprecise'], ['range', 'swatchrange'], ['uncertain', 'swatchuncertain']].forEach(function (k) {
          var li = el('li'), sw = el('span', 'atlas-swatch atlas-swatch--' + k[0]); sw.setAttribute('aria-hidden', 'true');
          li.appendChild(sw); li.appendChild(document.createTextNode(T[k[1]])); key.appendChild(li);
        });
        body.appendChild(key);
        built = true;
        sync(current());
      }
      function slider(label, value) {
        var s = el('input'); s.type = 'range'; s.min = lo; s.max = hi; s.step = 1; s.value = value;
        s.setAttribute('aria-label', label);
        s.addEventListener('input', function () {
          var a = parseInt(fromIn.value, 10), b = parseInt(toIn.value, 10);
          if (a > b) { if (s === fromIn) fromIn.value = b; else toIn.value = a; }
          clearTimeout(timer);
          timer = setTimeout(function () {         // the shared period: the timeline follows. One history step per drag.
            store.set({ from: parseInt(fromIn.value, 10) > lo ? fromIn.value : '', to: parseInt(toIn.value, 10) < hi ? toIn.value : '' },
                      dragging ? 'replace' : 'push');
            dragging = true;
          }, 150);
        });
        s.addEventListener('change', function () { dragging = false; });
        return s;
      }
      function sync(f) {
        var a = f.from || null, b = f.to || null;
        rangeEl.textContent = a || b ? fmt(T.period, { from: a || '…', to: b || '…' }) : T.allperiods;
        if (!built) return;
        if (document.activeElement !== fromIn) fromIn.value = a ? Math.max(lo, Math.min(hi, a)) : lo;
        if (document.activeElement !== toIn) toIn.value = b ? Math.max(lo, Math.min(hi, b)) : hi;
        fromIn.setAttribute('aria-valuetext', String(a || lo)); toIn.setAttribute('aria-valuetext', String(b || hi));
        var x0 = a || lo, x1 = b || hi;
        groups.forEach(function (g, i) { g.setAttribute('class', lo + i < x0 || lo + i > x1 ? 'is-outside' : ''); });
      }
      return { build: build, sync: sync };
    })();
    document.getElementById('ribbon-timeline').addEventListener('click', function () {
      store.set({ mode: store.get().mode === 'both' ? 'both' : 'timeline' }, 'push');      // same period, other perspective
    });

    // ───────────── markers ─────────────
    function geojson(list) {
      return { type: 'FeatureCollection', features: list.map(function (p) {
        return { type: 'Feature', properties: { id: p.id }, geometry: { type: 'Point', coordinates: [p.lon, p.lat] } }; }) };
    }
    function pinElement(p) {
      var b = el('button', 'atlas-pin atlas-pin--' + p.precision + ' atlas-pin--' + p.category + (p.fictional ? ' atlas-pin--fictional' : ''));
      b.type = 'button';
      b.setAttribute('aria-label', p.name + ' — ' + p.type_label + ' — ' + p.precision_label + (p.disputed ? ' — ' + T.disputedshort : ''));
      b.appendChild(mark(p.category, p.precision, MARK_SIZE[p.precision] || 22));
      if (p.disputed) b.appendChild(disputeMark());
      var lab = el('span', 'atlas-pin__label', p.name); lab.dir = 'auto'; lab.setAttribute('aria-hidden', 'true');
      b.appendChild(lab);
      b.addEventListener('click', function (e) { e.stopPropagation(); choosePlace(p, b); });
      b._place = p;
      return b;
    }
    // MapLibre labels every marker element "Map marker"; give each back its real accessible name
    function labelled(m, label) { m._label = label; return m; }   // applied after addTo(), which is where MapLibre sets its own
    function placeMarker(p) {
      var b = pinElement(p);
      return labelled(new maplibregl.Marker({ element: b, anchor: 'center' }).setLngLat([p.lon, p.lat]), b.getAttribute('aria-label'));
    }
    function clusterMarker(f) {
      var n = f.properties.point_count, b = el('button', 'atlas-cluster' + (n >= 10 ? ' atlas-cluster--l' : ''), String(n));
      b.type = 'button'; b.setAttribute('aria-label', fmt(T.cluster, { n: n }));
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        map.getSource('places').getClusterExpansionZoom(f.properties.cluster_id).then(function (z) {
          map.easeTo({ center: f.geometry.coordinates, zoom: Math.min(z + 0.3, map.getMaxZoom()), duration: reduce ? 0 : 500 });
        });
      });
      return labelled(new maplibregl.Marker({ element: b, anchor: 'center' }).setLngLat(f.geometry.coordinates), fmt(T.cluster, { n: n }));
    }
    function clearMarkers() { for (var id in onScreen) onScreen[id].remove(); markers = {}; onScreen = {}; schedule(); }
    function updateMarkers() {
      if (!mapReady) return;
      var next = {};
      map.querySourceFeatures('places').forEach(function (f) {
        var pr = f.properties, id = pr.cluster ? 'c' + pr.cluster_id : 'p' + pr.id;
        if (next[id]) return;
        var m = markers[id];
        if (!m) {
          if (pr.cluster) m = clusterMarker(f); else if (byId[pr.id]) m = placeMarker(byId[pr.id]); else return;
          markers[id] = m;
        }
        next[id] = m;
        if (!onScreen[id]) { m.addTo(map); if (m._label) m.getElement().setAttribute('aria-label', m._label); }
      });
      for (var id in onScreen) if (!next[id]) onScreen[id].remove();
      onScreen = next;
      refreshMarkers();
    }
    function pinElements() {
      var out = [];
      if (mapReady) for (var id in onScreen) out.push(onScreen[id].getElement());
      if (flat) out = out.concat(flat.pins());
      return out;
    }
    function refreshMarkers() {
      var many = shown.length > 12 && (!mapReady || map.getZoom() < 7);      // at country level, not every name at once
      pinElements().forEach(function (b) {
        var p = b._place; if (!p) return;
        var isSel = !!selected && selected.id === p.id, isRel = !!related && related.indexOf(p.id) >= 0;
        b.classList.toggle('is-selected', isSel);
        b.classList.toggle('is-related', isRel);
        b.classList.toggle('is-dimmed', !!related && related.length > 0 && !isRel && !isSel);
        b.classList.toggle('is-quiet', many && !isSel && !isRel);
      });
      collide();
    }

    // labels never pile up: selected place, archive places, the capital, regions, then other towns
    function collide() {
      var taken = [];
      function free(r) {
        for (var i = 0; i < taken.length; i++) {
          var t = taken[i];
          if (r.left < t.right + 3 && r.right + 3 > t.left && r.top < t.bottom + 1 && r.bottom + 1 > t.top) return false;
        }
        return true;
      }
      function place(elm, label) {
        if (!label || elm.classList.contains('is-off')) return;
        label.classList.remove('is-collided');
        var r = label.getBoundingClientRect();
        if (!r.width) return;
        if (free(r)) taken.push(r); else label.classList.add('is-collided');
      }
      var all = pinElements(), pins = all.filter(function (b) { return b.classList.contains('atlas-pin'); });
      all.forEach(function (b) { var g = b.querySelector('.atlas-mark') || b; taken.push(g.getBoundingClientRect()); });
      pins.sort(function (a, b) { return b.classList.contains('is-selected') - a.classList.contains('is-selected'); });
      pins.forEach(function (b) { place(b, b.querySelector('.atlas-pin__label')); });
      var capitals = townMarkers.filter(function (m) { return m.getElement().classList.contains('atlas-town--capital'); });
      capitals.forEach(function (m) { var e = m.getElement(); place(e, e.querySelector('.atlas-town__label')); });
      regionMarkers.forEach(function (m) { var e = m.getElement(); place(e, e); });
      townMarkers.forEach(function (m) { if (capitals.indexOf(m) < 0) { var e = m.getElement(); place(e, e.querySelector('.atlas-town__label')); } });
    }
    var queued = false;
    function schedule() {
      if (queued || !mapReady) return;
      queued = true;
      window.requestAnimationFrame(function () { queued = false; updateMarkers(); });
    }

    // ───────────── camera ─────────────
    function cameraNow() { return mapReady ? { center: map.getCenter(), zoom: map.getZoom(), bearing: map.getBearing(), pitch: map.getPitch() } : null; }
    function camera() {
      var w = map.getContainer().clientWidth, small = w < 500;
      var c = map.cameraForBounds(ERITREA, { padding: small ? { top: 20, bottom: 20, left: 10, right: 56 } : { top: 40, bottom: 40, left: 40, right: 70 } });
      if (small) return { center: c.center, zoom: c.zoom - 0.15, bearing: 0, pitch: is3d ? 32 : 0 };   // a gentler tilt keeps the whole country in view
      return { center: c.center, zoom: c.zoom + (is3d && w > 700 ? 0.45 : 0), bearing: is3d ? BEARING : 0, pitch: is3d ? PITCH : 0 };
    }
    function resetView(animate) {
      if (!mapReady) return;
      var c = camera();
      if (animate && !reduce) map.flyTo(Object.assign(c, { duration: 1200 })); else map.jumpTo(c);
    }
    // Ordinary selections move briefly; a long move flies. Approximate places are never zoomed to as if exact.
    function moveTo(p) {
      if (!mapReady || !visible()) return;
      var z = p.precision === 'region_centroid' ? 7.4 : p.precision === 'approximate' ? 8.4 : Math.min(11, Math.max(map.getZoom(), 9.6));
      var target = { center: [p.lon, p.lat], zoom: z, padding: sheetPadding() };
      if (reduce) return map.jumpTo(target);
      var near = map.getBounds().contains([p.lon, p.lat]) && Math.abs(map.getZoom() - z) < 2;
      if (near) map.easeTo(Object.assign(target, { duration: 550 })); else map.flyTo(Object.assign(target, { duration: 1100, essential: false }));
    }
    function fitPlaces(list) {
      if (!mapReady || !list.length || !visible()) return;
      if (list.length === 1) return moveTo(list[0]);
      var b = new maplibregl.LngLatBounds();
      list.forEach(function (p) { b.extend([p.lon, p.lat]); });
      map.fitBounds(b, { padding: 90, maxZoom: 9, duration: reduce ? 0 : 900, pitch: map.getPitch(), bearing: map.getBearing() });
    }
    function fitShown() { if (!mapReady) return; if (!shown.length) resetView(true); else fitPlaces(shown); }
    function set3d(on) {
      is3d = on && !terrainFailed;
      prefs.set('elf-atlas-3d', is3d ? '1' : '0');
      controls.querySelector('[data-act="terrain"]').setAttribute('aria-pressed', String(is3d));
      map.setTerrain(is3d ? { source: 'dem', exaggeration: EXAGGERATION } : null);
      map.easeTo({ pitch: is3d ? PITCH : 0, bearing: is3d ? (map.getBearing() || BEARING) : 0, duration: reduce ? 0 : 800 });
    }

    // ───────────── base map ─────────────
    function addBasemap(b) {
      map.addSource('countries', { type: 'geojson', data: b.countries });
      map.addSource('regions', { type: 'geojson', data: b.regions });
      map.addSource('rivers', { type: 'geojson', data: b.rivers });
      var before = 'places-hit';
      map.addLayer({ id: 'land', type: 'fill', source: 'countries',
        paint: { 'fill-color': ['case', ['==', ['get', 'code'], 'ERI'], C('land-er'), C('land')] } }, before);
      if (tile) {
        map.addSource('street', { type: 'raster', tiles: [tile], tileSize: 256, attribution: tileAttribution });
        map.addLayer({ id: 'street', type: 'raster', source: 'street', layout: { visibility: 'none' },
          paint: { 'raster-opacity': 0.55, 'raster-saturation': -0.7, 'raster-brightness-max': 0.6 } }, before);
      }
      if (!terrainFailed) map.addLayer({ id: 'relief', type: 'hillshade', source: 'shade',
        paint: { 'hillshade-shadow-color': C('shade-dark'), 'hillshade-highlight-color': C('shade-light'),
                 'hillshade-accent-color': C('shade-accent'), 'hillshade-exaggeration': 0.6,
                 'hillshade-illumination-direction': 315, 'hillshade-illumination-anchor': 'map' } }, before);
      map.addLayer({ id: 'borders', type: 'line', source: 'countries', filter: ['!=', ['get', 'code'], 'ERI'],
        paint: { 'line-color': C('border'), 'line-width': 0.8 } }, before);
      map.addLayer({ id: 'rivers', type: 'line', source: 'rivers',
        paint: { 'line-color': C('river'), 'line-width': ['interpolate', ['linear'], ['zoom'], 5, 0.6, 10, 1.8] } }, before);
      map.addLayer({ id: 'regions', type: 'line', source: 'regions',
        paint: { 'line-color': C('region'), 'line-width': 1, 'line-dasharray': [3, 3] } }, before);
      map.addLayer({ id: 'eritrea', type: 'line', source: 'countries', filter: ['==', ['get', 'code'], 'ERI'],
        paint: { 'line-color': C('er-line'), 'line-width': ['interpolate', ['linear'], ['zoom'], 5, 1.1, 10, 2.2], 'line-opacity': 0.9 } }, before);
      b.regions.features.forEach(function (f) {
        var box = new maplibregl.LngLatBounds();
        (f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates).forEach(function (poly) {
          poly[0].forEach(function (c) { box.extend(c); }); });
        var lab = el('span', 'atlas-region-label', f.properties.name); lab.setAttribute('aria-hidden', 'true');
        var rm = new maplibregl.Marker({ element: lab, anchor: 'center' }).setLngLat(box.getCenter()).addTo(map);
        lab.removeAttribute('aria-label'); regionMarkers.push(rm);
      });
      b.towns.features.forEach(function (f) {
        if (!f.properties.eri && f.properties.rank > 3) return;
        var d = el('div', 'atlas-town' + (f.properties.capital && f.properties.eri ? ' atlas-town--capital' : ''));   // only Asmara is emphasised
        d.setAttribute('aria-hidden', 'true');
        d.appendChild(el('span', 'atlas-town__label', f.properties.name));
        var tm = new maplibregl.Marker({ element: d, anchor: 'center' }).setLngLat(f.geometry.coordinates).addTo(map);
        d.removeAttribute('aria-label'); townMarkers.push(tm);
      });
      schedule();
    }
    // Reviewers only: proposed places and proposed location changes awaiting a decision (never in the public data).
    var proposals = [];
    function showProposals(on) {
      proposals.forEach(function (m) { m.remove(); });
      proposals = [];
      if (!on) return;
      getJSON('/map/review.json').then(function (d) {
        if (!d.proposals.length) { note(T.noproposals); return; }
        d.proposals.forEach(function (x) {
          var a = el('a', 'atlas-proposal'); a.href = x.url;
          var label = fmt(x.change ? T.proposedchange : T.proposedplace, { name: x.title || '?' });
          var lab = el('span', 'atlas-pin__label', label); lab.dir = 'auto'; lab.setAttribute('aria-hidden', 'true'); a.appendChild(lab);
          var m = new maplibregl.Marker({ element: a, anchor: 'center' }).setLngLat([x.lon, x.lat]).addTo(map);
          a.setAttribute('aria-label', label + ' — ' + T.awaitingreview); a.title = T.awaitingreview;
          proposals.push(m);
        });
      }).catch(function () { note(T.error); });
    }
    function setLayer(name, on) {
      if (name === 'evplaces' || name === 'otherplaces') { layerOn[name] = on; redraw(); return; }
      if (name === 'proposals') { showProposals(on); return; }
      if (name === 'towns') townMarkers.forEach(function (m) { m.getElement().classList.toggle('is-off', !on); });
      if (name === 'regions') regionMarkers.forEach(function (m) { m.getElement().classList.toggle('is-off', !on); });
      var layer = { regions: 'regions', rivers: 'rivers', relief: 'relief', street: 'street' }[name];
      if (layer && map.getLayer(layer)) map.setLayoutProperty(layer, 'visibility', on ? 'visible' : 'none');
      schedule();
    }
    function terrainUnavailable() {          // elevation tiles missing: carry on with a flat map, and say so
      if (terrainFailed) return;
      terrainFailed = true; is3d = false;
      map.setTerrain(null);
      if (map.getLayer('relief')) map.setLayoutProperty('relief', 'visibility', 'none');
      map.easeTo({ pitch: 0, bearing: 0, duration: 0 });
      var t = controls.querySelector('[data-act="terrain"]'); t.setAttribute('aria-pressed', 'false'); t.disabled = true;
      note(T.noterrain);
    }

    function initMap() {
      maplibregl.setWorkerUrl(root.getAttribute('data-worker'));
      var basemapPromise = getJSON('/map/basemap.json');
      var dem = { type: 'raster-dem', tiles: [window.location.origin + root.getAttribute('data-terrain') + '/{z}/{x}/{y}.png'],
                  encoding: 'terrarium', tileSize: 256, minzoom: 5, maxzoom: 9, bounds: DEM_BOUNDS };
      try {
        map = new maplibregl.Map({
          container: 'map',
          style: { version: 8, sources: { dem: dem, shade: Object.assign({}, dem) },
                   layers: [{ id: 'sea', type: 'background', paint: { 'background-color': C('sea') } }],
                   sky: { 'sky-color': C('sky'), 'horizon-color': C('horizon'), 'fog-color': C('sea'),
                          'sky-horizon-blend': 0.6, 'horizon-fog-blend': 0.7, 'fog-ground-blend': 0.75, 'atmosphere-blend': 0 } },
          bounds: ERITREA, maxBounds: [[33.8, 9.8], [45.7, 20.7]], minZoom: 5, maxZoom: tile ? 16 : 12.5, maxPitch: 72,
          attributionControl: false, fadeDuration: reduce ? 0 : 250, pixelRatio: Math.min(window.devicePixelRatio || 1, 2),
          locale: { 'Map.Title': T.maplabel }
        });
      } catch (e) { map = null; return startFlat(T.nowebgl); }
      map.addControl(new maplibregl.AttributionControl({ compact: true,
        customAttribution: [T.attribution, T.terrain].concat(tileAttribution ? [tileAttribution] : []) }), rtl ? 'bottom-left' : 'bottom-right');
      // touch: pan and pinch-zoom only, so tapping a marker never rotates or tilts the map; 3D and "face north" are buttons
      map.touchZoomRotate.disableRotation();
      map.touchPitch.disable();

      map.on('load', function () {
        map.addSource('places', { type: 'geojson', data: geojson(onMap()), cluster: true, clusterRadius: 46, clusterMaxZoom: 10 });
        map.addLayer({ id: 'places-hit', type: 'circle', source: 'places', paint: { 'circle-radius': 1, 'circle-opacity': 0, 'circle-stroke-opacity': 0 } });
        if (is3d) map.setTerrain({ source: 'dem', exaggeration: EXAGGERATION });
        mapReady = true;
        view.classList.add('is-live');
        controls.hidden = false;
        controls.querySelector('[data-act="terrain"]').setAttribute('aria-pressed', String(is3d));
        resetView(false);
        var attrib = map.getContainer().querySelector('.maplibregl-ctrl-attrib');
        if (attrib) attrib.classList.remove('maplibregl-compact-show');
        note(T.loadingterrain);
        // is elevation data there at all? (a 404 tile is not always reported as an error by the map library)
        fetch(root.getAttribute('data-terrain') + '/5/19/14.png', { method: 'HEAD' })
          .then(function (r) { if (!r.ok) terrainUnavailable(); }).catch(terrainUnavailable);
        map.once('idle', function () { if (toast.textContent === T.loadingterrain) note(''); });   // (a failure notice stays)
        basemapPromise.then(addBasemap).catch(function () { /* archive places still work without the base layers */ });
        redraw();
        panelKey = ''; syncSelection();          // the camera can now follow the selection
        schedule();
      });
      map.on('render', schedule);
      map.on('zoomend', refreshMarkers);
      map.on('rotate', function () { controls.querySelector('.atlas-compass').style.transform = 'rotate(' + (-map.getBearing()) + 'deg)'; });
      map.on('error', function (e) {
        if (e && (e.sourceId === 'dem' || e.sourceId === 'shade') && ++demErrors >= 3) terrainUnavailable();
      });
      map.on('webglcontextlost', function () {
        mapReady = false;
        try { map.remove(); } catch (e) { /* already gone */ }
        map = null; startFlat(T.lost);
      });
      window.addEventListener('pagehide', function () { if (map) map.remove(); });
    }

    // ───────────── flat fallback (no WebGL): the same base map as simple shapes, with the same place buttons ─────────────
    function startFlat(msg) {
      view.classList.add('is-failed');
      controls.hidden = true; fallback.hidden = true;
      note(msg);
      var box = el('div', 'atlas-flat');
      document.getElementById('map').appendChild(box);
      var B = [35.6, 11.9, 43.8, 18.6], kx = Math.cos(15.2 * Math.PI / 180);
      var W = (B[2] - B[0]) * kx * 100, H = (B[3] - B[1]) * 100;
      var proj = function (c) { return [(c[0] - B[0]) * kx * 100, (B[3] - c[1]) * 100]; };
      var svg = svgEl('svg', { viewBox: '0 0 ' + W.toFixed(0) + ' ' + H.toFixed(0), preserveAspectRatio: 'xMidYMid meet', 'aria-hidden': 'true' });
      box.appendChild(svg);
      function path(geom, cls) {
        var polys = geom.type === 'Polygon' ? [geom.coordinates] : geom.type === 'MultiPolygon' ? geom.coordinates : [];
        var d = polys.map(function (poly) { return poly.map(function (ring) {
          return 'M' + ring.map(function (c) { var xy = proj(c); return xy[0].toFixed(1) + ' ' + xy[1].toFixed(1); }).join('L') + 'Z'; }).join(''); }).join('');
        if (d) svg.appendChild(svgEl('path', { d: d, 'class': cls }));
      }
      getJSON('/map/basemap.json').then(function (b) {
        b.countries.features.forEach(function (f) { path(f.geometry, f.properties.code === 'ERI' ? 'f-eri' : 'f-land'); });
        b.regions.features.forEach(function (f) { path(f.geometry, 'f-region'); });
      }).catch(function () { /* the place buttons still work */ });
      flat = {
        draw: function () {
          box.querySelectorAll('.atlas-pin').forEach(function (n) { n.remove(); });
          var rect = box.getBoundingClientRect(), s = Math.min(rect.width / W, rect.height / H) || 1;
          var ox = (rect.width - W * s) / 2, oy = (rect.height - H * s) / 2;
          onMap().forEach(function (p) {
            if (p.lon < B[0] || p.lon > B[2] || p.lat < B[1] || p.lat > B[3]) return;
            var xy = proj([p.lon, p.lat]), b = pinElement(p);
            b.style.left = (ox + xy[0] * s) + 'px'; b.style.top = (oy + xy[1] * s) + 'px';
            box.appendChild(b);
          });
          refreshMarkers();
        },
        pins: function () { return Array.prototype.slice.call(box.querySelectorAll('.atlas-pin')); }
      };
      window.addEventListener('resize', function () { if (visible()) flat.draw(); });
      flat.draw();
    }
    function startMap() {            // the 3D map (and its 730 KB library) is loaded only when the map is shown
      if (mapStarted) { if (map) map.resize(); if (flat) flat.draw(); return; }
      mapStarted = true;
      if (!webglOK()) return startFlat(T.nowebgl);
      if (window.maplibregl) return initMap();
      var s = document.createElement('script');
      s.src = root.getAttribute('data-lib');
      s.onload = function () { if (window.maplibregl) initMap(); else startFlat(T.nowebgl); };
      s.onerror = function () { startFlat(T.nowebgl); };
      document.head.appendChild(s);
    }

    // ───────────── controls ─────────────
    var fsBtn = controls.querySelector('[data-act="fullscreen"]');
    if (document.fullscreenEnabled && root.requestFullscreen) fsBtn.hidden = false;
    document.addEventListener('fullscreenchange', function () {
      fsBtn.setAttribute('aria-pressed', String(document.fullscreenElement === root));
      if (map) setTimeout(function () { map.resize(); }, 50);
    });
    controls.addEventListener('click', function (e) {
      var b = e.target.closest('[data-act]');
      if (!b || !mapReady) return;
      var act = b.getAttribute('data-act'), d = reduce ? 0 : 300;
      if (act === 'zoom-in') map.zoomIn({ duration: d });
      else if (act === 'zoom-out') map.zoomOut({ duration: d });
      else if (act === 'terrain') set3d(!is3d);
      else if (act === 'north') map.easeTo({ bearing: 0, pitch: 0, duration: reduce ? 0 : 500 });
      else if (act === 'reset') resetView(true);
      else if (act === 'fullscreen') { if (document.fullscreenElement) document.exitFullscreen(); else root.requestFullscreen(); }
      else if (act === 'layers') {
        var menu = document.getElementById('atlas-layer-menu'), open = menu.hidden;
        menu.hidden = !open; b.setAttribute('aria-expanded', String(open));
        if (open) menu.querySelector('input').focus();
      }
    });
    controls.addEventListener('change', function (e) { var l = e.target.getAttribute('data-layer'); if (l && mapReady) setLayer(l, e.target.checked); });
    controls.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      var menu = document.getElementById('atlas-layer-menu');
      if (!menu.hidden) { menu.hidden = true; var t = controls.querySelector('[data-act="layers"]'); t.setAttribute('aria-expanded', 'false'); t.focus(); }
    });
    document.getElementById('map-fit').addEventListener('click', fitShown);

    // ───────────── the shared state drives everything ─────────────
    store.subscribe(function (s, changed, meta) {
      if (!dataReady) { if (changed.indexOf('mode') >= 0 && visible()) loadData(); return; }
      var filt = changed.some(function (k) { return FILTER_KEYS.indexOf(k) >= 0; });
      if (changed.indexOf('mode') >= 0 && visible()) startMap();
      if (filt) { apply(false); if (changed.indexOf('q') >= 0) runSearch(); }
      if (changed.some(function (k) { return k === 'place' || k === 'event' || k === 'record'; })) { panelKey = changed.indexOf('place') >= 0 ? '' : panelKey; syncSelection(); }
      else if (filt && selected) { panelKey = ''; syncSelection(); }       // re-check "outside the current filters"
      if (meta.reason === 'clear') resetView(true);                         // cleared: back to the national overview
    });

    // the places are loaded when the map is first shown (not while only the timeline is on screen)
    var loading = false;
    function loadData() {
      if (loading) return;
      loading = true;
      getJSON('/map/data.json').then(function (data) {
      places = data.places.filter(validLL);
      places.forEach(function (p) { byId[p.id] = p; });
      dataReady = true;
      ribbon.build();
      apply(false);
      if (store.get().q) runSearch();
      if (visible()) startMap();
      syncSelection();
      }).catch(function () {
        say(T.error);
        view.classList.add('is-failed');
        fallback.querySelector('span:last-child').textContent = T.error;
      });
    }
    if (visible()) loadData();
  });
})();
