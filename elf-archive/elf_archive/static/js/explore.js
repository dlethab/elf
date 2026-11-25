// The explore page's shared controls: the filter bar, the active-filter chips, the map / timeline mode switch and
// the "events at this place" context. They read and write the one exploration store (atlas-state.js); the map and
// the timeline subscribe to the same store, so a change made anywhere is reflected everywhere.
(function () {
  'use strict';
  var S = window.AtlasState;
  function ready(fn) { if (document.readyState !== 'loading') fn(); else document.addEventListener('DOMContentLoaded', fn); }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function fmt(s, v) { return s.replace(/\{(\w+)\}/g, function (_, k) { return v[k]; }); }

  ready(function () {
    var root = document.getElementById('explore');
    if (!root || !S) return;
    var T = JSON.parse(root.getAttribute('data-i18n'));
    var store = S.createStore(JSON.parse(root.getAttribute('data-state')), JSON.parse(root.getAttribute('data-labels') || '{}'));
    S.store = store;
    var form = document.getElementById('ex-filters'), chips = document.getElementById('ex-chips');
    var modes = document.getElementById('ex-modes'), ctx = document.getElementById('ex-context'), title = document.getElementById('ex-title');
    var titles = JSON.parse(title.getAttribute('data-titles'));
    var narrow = window.matchMedia ? window.matchMedia('(max-width: 61.99rem)') : { matches: false };
    var timer, chipKey = '', ctxFor = null;

    form.classList.add('is-live');            // filters apply as they change: the submit button is only for pages without JavaScript
    // the selection lives in the store now, not in hidden fields
    form.querySelectorAll('[data-selection]').forEach(function (n) { n.remove(); });

    // ───────────── form → store ─────────────
    function fieldValue(name) {
      var f = form.elements[name];
      if (!f) return '';
      if (f.type === 'checkbox') return f.checked;
      if (f.getAttribute('data-lookup')) {
        var id = S.idOf(f.value);
        if (id) store.label(id, f.value.replace(S.PID, '').trim());
        return id;
      }
      return f.value;
    }
    form.addEventListener('input', function (e) {
      var n = e.target.name;
      if (!n || n === 'mode') return;
      if (e.target.getAttribute('data-lookup') && e.target.value && !S.idOf(e.target.value)) return;   // wait for a choice
      clearTimeout(timer);
      timer = setTimeout(function () { var p = {}; p[n] = fieldValue(n); store.set(p, 'replace'); }, n === 'q' ? 300 : 400);
    });
    form.addEventListener('change', function (e) {
      var n = e.target.name;
      if (!n || n === 'mode') return;
      if (e.target.getAttribute('data-lookup') && e.target.value && !S.idOf(e.target.value)) return;
      clearTimeout(timer);
      var p = {}; p[n] = fieldValue(n); store.set(p, 'push');
    });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var p = {};
      S.FILTERS.forEach(function (k) { p[k] = fieldValue(k); });
      store.set(p, 'push');
    });
    function clearAll() {
      var p = {};
      S.FILTERS.concat(S.SELECTION).forEach(function (k) { p[k] = ''; });
      p.media = false;
      store.set(p, 'push', { reason: 'clear' });
    }
    document.getElementById('ex-clear').addEventListener('click', function (e) { e.preventDefault(); clearAll(); });

    // ───────────── store → form, chips, mode, context ─────────────
    function syncForm(s) {
      S.FILTERS.forEach(function (k) {
        var f = form.elements[k];
        if (!f || f === document.activeElement) return;
        if (f.type === 'checkbox') f.checked = !!s[k];
        else if (f.getAttribute('data-lookup')) {
          if (S.idOf(f.value) !== s[k]) f.value = s[k] ? (store.labels[s[k]] || s[k]) + ' [' + s[k] + ']' : '';
        } else f.value = s[k] === null || s[k] === undefined ? '' : s[k];
      });
      form.elements.mode.value = s.mode;
    }
    function optionText(name, v) {
      var f = form.elements[name], o = f && Array.prototype.filter.call(f.options, function (x) { return x.value === v; })[0];
      return o ? o.text : v;
    }
    function renderChips(s) {
      var list = [];
      if (s.q) list.push(['q', fmt(T.chip_q, { v: s.q })]);
      if (s.type) list.push(['type', fmt(T.chip_type, { v: optionText('type', s.type) })]);
      if (s.from || s.to) list.push(['period', fmt(T.chip_period, { v: fmt(T.period, { from: s.from || '…', to: s.to || '…' }) })]);
      if (s.region) list.push(['region', fmt(T.chip_region, { v: s.region })]);
      if (s.at) list.push(['at', fmt(T.chip_at, { v: store.labels[s.at] || s.at })]);
      if (s.person) list.push(['person', fmt(T.chip_person, { v: store.labels[s.person] || s.person })]);
      if (s.organization) list.push(['organization', fmt(T.chip_org, { v: store.labels[s.organization] || s.organization })]);
      if (s.ptype) list.push(['ptype', fmt(T.chip_ptype, { v: optionText('ptype', s.ptype) })]);
      if (s.media) list.push(['media', T.chip_media]);
      var clear = document.getElementById('ex-clear'), more = document.getElementById('ex-more-count');
      clear.hidden = !list.length && !s.place && !s.event && !s.record;
      var adv = ['region', 'at', 'person', 'organization', 'ptype', 'media'].filter(function (k) { return !!s[k]; }).length;
      more.hidden = !adv; more.textContent = adv;
      var key = JSON.stringify(list);
      if (key === chipKey) return;                // a blur must not replace a chip that is being clicked
      chipKey = key; chips.textContent = '';
      list.forEach(function (c) {
        var li = el('li'), b = el('button', 'atlas-chip'); b.type = 'button';
        b.setAttribute('aria-label', fmt(T.removefilter, { v: c[1] }));
        b.appendChild(el('span', null, c[1]));
        var x = el('span', null, '×'); x.setAttribute('aria-hidden', 'true'); b.appendChild(x);
        b.addEventListener('click', function () {
          var p = {};
          if (c[0] === 'period') { p.from = ''; p.to = ''; } else p[c[0]] = c[0] === 'media' ? false : '';
          store.set(p, 'push');
          var next = chips.querySelector('button'); (next || form.elements.q).focus();
        });
        li.appendChild(b); chips.appendChild(li);
      });
      chips.hidden = !list.length;
    }
    function renderMode(s) {
      document.body.setAttribute('data-mode', s.mode);
      modes.querySelectorAll('[data-mode]').forEach(function (a) {
        var m = a.getAttribute('data-mode');
        if (m === s.mode) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
        a.href = S.href(Object.assign({}, s, { mode: m }));
      });
      title.textContent = titles[s.mode];
      var crumb = document.querySelector('.breadcrumbs [aria-current="page"]'); if (crumb) crumb.textContent = titles[s.mode];
      var parts = document.title.split(' · '); parts[0] = titles[s.mode]; document.title = parts.join(' · ');
    }
    function renderContext(s) {
      if (!s.at) { ctx.hidden = true; ctxFor = null; return; }
      if (ctxFor === s.at) { ctx.hidden = false; return; }
      ctxFor = s.at;
      fetch('/map/place/' + encodeURIComponent(s.at) + '.json').then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }).then(function (p) {
        if (store.get().at !== p.id) return;
        store.label(p.id, p.title);
        ctx.textContent = '';
        ctx.appendChild(el('span', 'atlas-kicker', T.ctx_kicker + ' · ' + p.type_label));
        var h = el('h2', null, p.title); h.dir = 'auto'; h.id = 'ctx-h'; ctx.appendChild(h);
        var loc = p.lat === null || p.lat === undefined ? T.nocoords : p.precision === 'approximate' ? T.approximate : p.precision === 'region_centroid' ? T.region : T.documented;
        ctx.appendChild(el('p', 'tl-context__meta', [p.region, loc].filter(Boolean).join(' · ')));
        if (p.summary) { var sm = el('p', null, p.summary); sm.dir = 'auto'; ctx.appendChild(sm); }
        var links = el('p', 'atlas-links');
        if (p.lat !== null && p.lat !== undefined) {
          var m = el('button', 'btn btn-small btn-secondary', T.ctx_map); m.type = 'button';
          m.addEventListener('click', function () { store.set({ mode: narrow.matches ? 'map' : (store.get().mode === 'both' ? 'both' : 'map'), place: p.id, event: '', record: '' }, 'push'); });
          links.appendChild(m);
        }
        var o = el('a', null, T.ctx_open); o.href = p.url; links.appendChild(o);
        var c = el('button', 'btn btn-small btn-secondary', T.ctx_clear); c.type = 'button';
        c.addEventListener('click', function () { store.set({ at: '' }, 'push'); });
        links.appendChild(c);
        ctx.appendChild(links);
        ctx.hidden = false;
        renderChips(store.get());          // the chip can now show the place's name
      }).catch(function () { ctx.hidden = true; store.set({ at: '' }, 'replace'); });
    }
    // ───────────── the period in the records: counts and most-linked records, never a narrative ─────────────
    var pctx = document.getElementById('ex-pctx'), PT = JSON.parse(pctx.getAttribute('data-i18n')), pKey = '', pSeq = 0;
    function renderPeriod(s) {
      var key = s.at || !(s.from || s.to) ? '' : [s.from, s.to, s.region, s.type].join('|');
      if (key === pKey) return;
      pKey = key; pctx.hidden = true;
      if (!key) return;
      var seq = ++pSeq, q = ['from', 'to', 'region', 'type'].filter(function (k) { return s[k]; })
        .map(function (k) { return k + '=' + encodeURIComponent(s[k]); }).join('&');
      fetch('/explore/context.json?' + q).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }).then(function (c) {
        if (seq !== pSeq) return;
        pctx.textContent = '';
        pctx.appendChild(el('span', 'atlas-kicker', PT.kicker));
        var h = el('h2', null, fmt(PT.title, { from: s.from || '…', to: s.to || '…' })); h.id = 'pctx-h'; pctx.appendChild(h);
        if (!c.n) { pctx.appendChild(el('p', 'tl-context__meta', PT.none)); pctx.hidden = false; return; }
        var meta = [c.n === 1 ? PT.count1 : fmt(PT.count, { n: c.n })];
        if (c.uncertain) meta.push(fmt(PT.uncertain, { n: c.uncertain }));
        pctx.appendChild(el('p', 'tl-context__meta', meta.join(' · ')));
        if (c.types.length) pctx.appendChild(el('p', 'small', PT.types + ': ' + c.types.map(function (t) { return t.label + ' (' + t.n + ')'; }).join(', ')));
        var more = el('details', 'ex-period__more'), sum = el('summary', null, [PT.events, PT.places, PT.people, PT.sources].filter(function (x, i) {
          return [c.events, c.places, c.people, c.sources][i].length; }).join(' · ') || PT.places);
        more.appendChild(sum);
        var grid = el('div', 'ex-period__grid');
        function block(title, items, extra) {
          if (!items || !items.length) return;
          var d = el('div'); d.appendChild(el('h3', 'atlas-label', title));
          var ul = el('ul', 'atlas-mini');
          items.forEach(function (it) {
            var li = el('li'), a = el('a', null, it.title); a.href = it.url; a.dir = 'auto'; li.appendChild(a);
            li.appendChild(el('span', 'small muted', ' · ' + (it.date ? it.date + ' · ' : '') + fmt(PT.times, { n: it.n })));
            if (extra) extra(li, it);
            ul.appendChild(li);
          });
          d.appendChild(ul); grid.appendChild(d);
        }
        block(PT.events + ' (' + PT.eventsnote + ')', c.events);
        block(PT.places, c.places, function (li, it) {
          if (!it.mapped) return;
          var b = el('button', 'linkish small', PT.onmap); b.type = 'button';
          b.addEventListener('click', function () { store.set({ mode: store.get().mode === 'timeline' ? 'map' : store.get().mode, place: it.id, event: '', record: '' }, 'push'); });
          li.appendChild(document.createTextNode(' ')); li.appendChild(b);
        });
        block(PT.people, c.people); block(PT.families, c.families); block(PT.collections, c.collections); block(PT.sources, c.sources);
        more.appendChild(grid); pctx.appendChild(more);
        var links = el('p', 'atlas-links');
        if (store.get().mode === 'map') {
          var tb = el('button', 'btn btn-small btn-secondary', PT.timeline); tb.type = 'button';
          tb.addEventListener('click', function () { store.set({ mode: 'timeline' }, 'push'); }); links.appendChild(tb);
        }
        links.appendChild(el('span', 'small muted', PT.note));
        pctx.appendChild(links);
        pctx.hidden = false;
      }).catch(function () { pctx.hidden = true; });
    }

    // server-rendered context buttons (before the store re-renders it)
    ctx.addEventListener('click', function (e) {
      var a = e.target.closest('[data-act]'); if (!a) return;
      e.preventDefault();
      if (a.getAttribute('data-act') === 'ctx-clear') store.set({ at: '' }, 'push');
      else store.set({ mode: 'map', place: store.get().at, event: '', record: '' }, 'push');
    });
    if (!ctx.hidden) ctxFor = store.get().at;

    modes.addEventListener('click', function (e) {
      var a = e.target.closest('[data-mode]'); if (!a) return;
      e.preventDefault();
      store.set({ mode: a.getAttribute('data-mode') }, 'push');
    });

    store.subscribe(function (s, changed) {
      syncForm(s); renderChips(s);
      if (changed.indexOf('mode') >= 0) renderMode(s);
      if (changed.indexOf('at') >= 0) renderContext(s);
      renderPeriod(s);
    });
    // a split view on a phone would make both halves too small: use the map there
    function fitMode() { if (narrow.matches && store.get().mode === 'both') store.set({ mode: 'map' }, 'replace'); }
    if (narrow.addEventListener) narrow.addEventListener('change', fitMode);
    fitMode();
    renderMode(store.get()); renderChips(store.get()); renderPeriod(store.get());
  });
})();
