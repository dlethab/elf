// The archive's plain reference map, shared by the location picker (forms) and the map on place pages.
// Flat (no 3D), built only from files on this server: the vendored MapLibre library, the Natural Earth base map
// (/map/basemap.json), the elevation tiles for relief shading, and published places (/map/places.json).
// Colours come from CSS custom properties (--lp-*) on the map's container, so light and dark themes both work.
(function () {
  'use strict';

  var ERITREA = [[36.43, 12.36], [43.14, 18.0]];
  var BOUNDS = [[31.5, 9.5], [47.5, 21.5]];             // the base map's extent
  var lib = null, basemap = null, places = null;

  function getJSON(url) { return fetch(url, { headers: { Accept: 'application/json' } }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }); }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

  window.ELFBasemap = {
    ERITREA: ERITREA, BOUNDS: BOUNDS,
    webglOK: function () {
      try { var c = document.createElement('canvas'); return !!(window.WebGLRenderingContext && (c.getContext('webgl2') || c.getContext('webgl'))); }
      catch (e) { return false; }
    },
    // the map library is loaded only when a map is actually needed
    load: function (src) {
      if (window.maplibregl) return Promise.resolve();
      if (!lib) lib = new Promise(function (ok, fail) {
        var s = document.createElement('script');
        s.src = src;
        s.onload = function () { if (window.maplibregl) ok(); else fail(new Error('no map library')); };
        s.onerror = fail;
        document.head.appendChild(s);
      });
      return lib;
    },
    places: function () { return places || (places = getJSON('/map/places.json').then(function (d) { return d.places; })); },
    // cfg: the element holding data-worker, data-terrain, data-tile, data-tile-attribution. o: { label, attribution, center, zoom, cooperative }
    make: function (container, cfg, o) {
      var css = window.getComputedStyle(container), C = function (n) { return css.getPropertyValue('--lp-' + n).trim(); };
      var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      maplibregl.setWorkerUrl(cfg.getAttribute('data-worker'));
      var dem = { type: 'raster-dem', tiles: [window.location.origin + cfg.getAttribute('data-terrain') + '/{z}/{x}/{y}.png'],
                  encoding: 'terrarium', tileSize: 256, minzoom: 5, maxzoom: 9, bounds: [35.0, 11.0, 44.5, 19.5] };
      var tile = JSON.parse(cfg.getAttribute('data-tile') || '""');
      var opts = {
        container: container, maxBounds: BOUNDS, minZoom: 4.5, maxZoom: tile ? 17 : 13,
        style: { version: 8, sources: { shade: dem }, layers: [{ id: 'sea', type: 'background', paint: { 'background-color': C('sea') } }] },
        attributionControl: false, dragRotate: false, pitchWithRotate: false, fadeDuration: reduce ? 0 : 200,
        cooperativeGestures: !!o.cooperative, locale: { 'Map.Title': o.label }
      };
      if (o.center) { opts.center = o.center; opts.zoom = o.zoom; } else opts.bounds = ERITREA;
      var map = new maplibregl.Map(opts);
      map.touchZoomRotate.disableRotation();
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
      map.addControl(new maplibregl.AttributionControl({ compact: true,
        customAttribution: [o.attribution].concat(tile ? [JSON.parse(cfg.getAttribute('data-tile-attribution') || '""')] : []) }));
      map.on('load', function () {
        (basemap || (basemap = getJSON('/map/basemap.json').catch(function () { return null; }))).then(function (b) {
          if (!b) return;
          map.addSource('countries', { type: 'geojson', data: b.countries });
          map.addSource('regions', { type: 'geojson', data: b.regions });
          map.addSource('rivers', { type: 'geojson', data: b.rivers });
          map.addLayer({ id: 'land', type: 'fill', source: 'countries', paint: { 'fill-color': ['case', ['==', ['get', 'code'], 'ERI'], C('land-er'), C('land')] } });
          if (tile) {            // an administrator-configured street layer: much finer detail
            map.addSource('street', { type: 'raster', tiles: [tile], tileSize: 256 });
            map.addLayer({ id: 'street', type: 'raster', source: 'street', paint: { 'raster-opacity': 0.85 } });
          }
          map.addLayer({ id: 'relief', type: 'hillshade', source: 'shade', paint: { 'hillshade-shadow-color': C('shade'), 'hillshade-highlight-color': C('light'), 'hillshade-exaggeration': 0.45 } });
          map.addLayer({ id: 'rivers', type: 'line', source: 'rivers', paint: { 'line-color': C('river'), 'line-width': 1 } });
          map.addLayer({ id: 'regions', type: 'line', source: 'regions', paint: { 'line-color': C('region'), 'line-width': 1, 'line-dasharray': [3, 3] } });
          map.addLayer({ id: 'borders', type: 'line', source: 'countries', paint: { 'line-color': C('border'), 'line-width': ['case', ['==', ['get', 'code'], 'ERI'], 1.6, 0.8] } });
          b.towns.features.forEach(function (f) {
            if (!f.properties.eri && f.properties.rank > 3) return;
            var d = el('div', 'locpick__town', f.properties.name); d.setAttribute('aria-hidden', 'true');
            new maplibregl.Marker({ element: d, anchor: 'left', offset: [3, 0] }).setLngLat(f.geometry.coordinates).addTo(map);
            d.removeAttribute('aria-label');
          });
        });
      });
      map.on('error', function () { /* a missing relief tile only leaves the map unshaded */ });
      return map;
    }
  };
})();
