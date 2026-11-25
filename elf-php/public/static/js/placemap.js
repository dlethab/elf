// The map on a place page: the place at its documented coordinates, drawn with its precision (an exact point,
// an approximate area, or only its region), and the other published places around it. Zoom depends on the
// precision, so an approximate place is never shown as if it were an exact point. Page scrolling is never captured
// (Ctrl + scroll or two fingers to zoom). Without JavaScript or WebGL the coordinates in the text are unchanged.
(function () {
  'use strict';
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function ready(fn) { if (document.readyState !== 'loading') fn(); else document.addEventListener('DOMContentLoaded', fn); }
  var ZOOM = { exact: 10, approximate: 8.4, region_centroid: 7 };

  ready(function () {
    var box = document.getElementById('place-map'), BM = window.ELFBasemap;
    if (!box || !BM || !window.fetch) return;
    var T = JSON.parse(box.getAttribute('data-i18n'));
    var me = { id: box.getAttribute('data-id'), lat: parseFloat(box.getAttribute('data-lat')), lon: parseFloat(box.getAttribute('data-lon')),
               precision: box.getAttribute('data-precision'), name: box.getAttribute('data-name') };
    if (!isFinite(me.lat) || !isFinite(me.lon)) return;
    box.hidden = false;
    var mapEl = box.querySelector('.place-map__map');
    if (!BM.webglOK()) { mapEl.replaceWith(el('p', 'locpick__note', T.nowebgl)); return; }
    BM.load(box.getAttribute('data-lib')).then(function () {
      var map = BM.make(mapEl, box, { label: T.maplabel, attribution: T.attribution, center: [me.lon, me.lat],
                                      zoom: ZOOM[me.precision] || 9, cooperative: true });
      map.on('load', function () {
        box.classList.add('is-live');
        // the other published places: small links to their own pages
        BM.places().then(function (ps) {
          ps.forEach(function (p) {
            if (p.id === me.id) return;
            var a = el('a', 'place-map__other'); a.href = '/id/' + encodeURIComponent(p.id);
            var lab = el('span', 'locpick__label', p.name); lab.dir = 'auto'; lab.setAttribute('aria-hidden', 'true'); a.appendChild(lab);
            new maplibregl.Marker({ element: a, anchor: 'center' }).setLngLat([p.lon, p.lat]).addTo(map);
            a.setAttribute('aria-label', p.name);
          });
        }).catch(function () { /* the place itself is still shown */ });
        // the place itself, on top
        var m = el('div', 'place-map__me place-map__me--' + me.precision); m.setAttribute('role', 'img');
        var lab = el('span', 'place-map__label', me.name); lab.dir = 'auto'; m.appendChild(lab);
        new maplibregl.Marker({ element: m, anchor: 'center' }).setLngLat([me.lon, me.lat]).addTo(map);
        m.setAttribute('aria-label', me.name + ' — ' + T[me.precision]);
        m.removeAttribute('tabindex');
      });
    }).catch(function () { mapEl.replaceWith(el('p', 'locpick__note', T.error)); });
  });
})();
