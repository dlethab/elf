// Shared exploration state for the historical atlas: one store used by the filter bar, the 3D map and the
// timeline on the explore page (/explore, also served at /map and /timeline).
//
// State (all public identifiers; the server drops anything that is not a public record before the page starts):
//   mode          'map' | 'timeline' | 'both'
//   q             search words (place names on the map, event titles and summaries on the timeline)
//   type          event type          from, to   period (years; an event matches if its documented span overlaps)
//   region        administrative region of an event's or place's documented place
//   media         only records with photographs, documents or oral histories
//   ptype         place type or 'cat:<category>' (map only)
//   at            place FILTER: events documented at this place
//   person, organization   filters through documented participation or affiliation
//   place         selected place (map)     event   selected event     record   selected other record
//
// The address mirrors the state (/explore?mode=…&from=…). Deliberate actions add a history entry (push), so the
// browser's back and forward buttons step through the exploration; continuous input (typing, dragging the period)
// replaces the current entry. Camera movements are never written. Subscribers receive the changed keys only, and
// setting a value it already has does nothing, so the map and the timeline cannot echo changes back and forth.
(function () {
  'use strict';
  var PID = /\[([a-z]{3}-[a-z0-9]{8})\]\s*$/;
  var BARE = /^[a-z]{3}-[a-z0-9]{8}$/;
  var KEYS = ['mode', 'q', 'type', 'from', 'to', 'region', 'media', 'ptype', 'at', 'person', 'organization', 'place', 'event', 'record'];
  var IDS = ['at', 'person', 'organization', 'place', 'event', 'record'];
  var FILTERS = ['q', 'type', 'from', 'to', 'region', 'media', 'ptype', 'at', 'person', 'organization'];
  var SELECTION = ['place', 'event', 'record'];

  function idOf(v) {                    // "Name [per-abc12345]" or a bare permanent id → the id
    v = (v || '').trim();
    var m = PID.exec(v);
    return m ? m[1] : BARE.test(v) ? v : '';
  }
  function norm(s) {
    return (s || '').normalize('NFKD').replace(/[̀-ًͯ-ٟ]/g, '').replace(/['’‘ʼʻʿʾ`´]/g, '')
      .toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
  }
  function year(v) { var y = parseInt(v, 10); return y >= 1000 && y <= 2100 ? y : null; }

  function clean(s) {
    var out = {};
    KEYS.forEach(function (k) {
      var v = s[k];
      if (k === 'from' || k === 'to') out[k] = year(v);
      else if (k === 'media') out[k] = v === true || v === '1' || v === 1;
      else if (IDS.indexOf(k) >= 0) out[k] = idOf(v);
      else if (k === 'mode') out[k] = ['map', 'timeline', 'both'].indexOf(v) >= 0 ? v : 'map';
      else out[k] = (v || '').toString().slice(0, 100);
    });
    return out;
  }

  // Does an event fall in the period? Its documented span must overlap it; an undated event never does.
  function inPeriod(ev, f) {
    if (!f.from && !f.to) return true;
    return ev.from !== null && ev.from !== undefined && (!f.from || ev.to >= f.from) && (!f.to || ev.from <= f.to);
  }
  function eventMatches(ev, f) {
    if (f.type && ev.type !== f.type) return false;
    if (!inPeriod(ev, f)) return false;
    if (f.at && !(ev.places || []).some(function (p) { return p.id === f.at; })) return false;
    if (f.region && !(ev.places || []).some(function (p) { return p.region === f.region; })) return false;
    if (f.person && (ev.persons || []).indexOf(f.person) < 0) return false;
    if (f.organization && (ev.orgs || []).indexOf(f.organization) < 0) return false;
    if (f.media && !ev.media) return false;
    if (f.q && (norm(ev.title) + ' ' + norm(ev.summary)).indexOf(norm(f.q)) < 0) return false;
    return true;
  }

  function toQuery(s) {
    var q = new URLSearchParams();
    KEYS.forEach(function (k) { var v = s[k]; if (v === true) v = '1'; if (v) q.set(k, v); });
    return q.toString();
  }
  // shown inside another site (?embed=1, see /explore in web/public.py): every address keeps the embedded layout
  var EMBED = /(?:^|[?&])embed=1(?:&|$)/.test(window.location.search);
  function href(s) { var q = toQuery(clean(s)); return '/explore?' + [q, EMBED ? 'embed=1' : ''].filter(Boolean).join('&'); }
  function fromQuery(search) {
    var p = new URLSearchParams(search), o = {};
    KEYS.forEach(function (k) { o[k] = p.get(k) || ''; });
    return clean(o);
  }

  function createStore(initial, labels) {
    var state = clean(initial || {}), subs = [];
    var store = {
      labels: labels || {},                 // id → display name, for chips (never written to the address)
      get: function () { return Object.assign({}, state); },
      subscribe: function (fn) { subs.push(fn); return function () { subs = subs.filter(function (f) { return f !== fn; }); }; },
      // how: 'push' (a step the back button returns to), 'replace' (continuous input), 'none' (already in the address)
      set: function (patch, how, meta) {
        var next = clean(Object.assign({}, state, patch)), changed = KEYS.filter(function (k) { return next[k] !== state[k]; });
        if (!changed.length) return false;
        state = next;
        if (how !== 'none') {
          try { window.history[how === 'push' ? 'pushState' : 'replaceState']({ atlas: state }, '', href(state)); } catch (e) { /* not essential */ }
        }
        subs.slice().forEach(function (fn) { fn(store.get(), changed, meta || {}); });
        return true;
      },
      label: function (id, text) { if (id && text) store.labels[id] = text; }
    };
    window.addEventListener('popstate', function (e) {       // back / forward: restore that step of the exploration
      var s = e.state && e.state.atlas ? e.state.atlas : fromQuery(window.location.search);
      store.set(s, 'none', { reason: 'history' });
    });
    try { window.history.replaceState({ atlas: state }, '', href(state)); } catch (e) { /* not essential */ }
    return store;
  }

  window.AtlasState = { PID: PID, idOf: idOf, norm: norm, year: year, inPeriod: inPeriod, eventMatches: eventMatches,
                        href: href, fromQuery: fromQuery, createStore: createStore,
                        KEYS: KEYS, FILTERS: FILTERS, SELECTION: SELECTION, store: null };
})();
