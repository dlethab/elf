// Pan and zoom for server-rendered SVG diagrams (family trees, connections). Works with a mouse,
// touch (drag and pinch), and the keyboard (arrow keys, + and −). Without JavaScript the full diagram
// is shown at its natural size, with a list alternative below it. Only the SVG viewBox changes.
(function () {
  'use strict';
  function ready(fn) { if (document.readyState !== 'loading') fn(); else document.addEventListener('DOMContentLoaded', fn); }
  ready(function () {
    document.querySelectorAll('[data-graph]').forEach(function (box) {
      var vp = box.querySelector('.graph__viewport'), svg = box.querySelector('svg.graph__svg');
      if (!vp || !svg) return;
      var W = +svg.getAttribute('data-w'), H = +svg.getAttribute('data-h');
      var view = { x: 0, y: 0, w: W, h: H };
      box.classList.add('graph--live');
      function aspect() { var r = vp.getBoundingClientRect(); return r.height ? r.width / r.height : 1.6; }
      function set() { svg.setAttribute('viewBox', [view.x, view.y, view.w, view.h].map(Math.round).join(' ')); }
      function fit() {
        var a = aspect();
        if (W / H > a) { view.w = W; view.h = W / a; view.x = 0; view.y = (H - view.h) / 2; }
        else { view.h = H; view.w = H * a; view.y = 0; view.x = (W - view.w) / 2; }
        set();
      }
      function zoom(f, cx, cy) {
        var nw = Math.min(Math.max(view.w * f, W / 12), W * 4), nh = nw * view.h / view.w;
        cx = cx === undefined ? view.x + view.w / 2 : cx; cy = cy === undefined ? view.y + view.h / 2 : cy;
        view.x = cx - (cx - view.x) * nw / view.w; view.y = cy - (cy - view.y) * nh / view.h; view.w = nw; view.h = nh; set();
      }
      function toSvg(clientX, clientY) {
        var r = svg.getBoundingClientRect();
        return { x: view.x + (clientX - r.left) / r.width * view.w, y: view.y + (clientY - r.top) / r.height * view.h };
      }
      box.querySelectorAll('[data-zoom]').forEach(function (b) {
        b.addEventListener('click', function () {
          var z = b.getAttribute('data-zoom');
          if (z === 'fit') fit(); else zoom(z === 'in' ? 0.75 : 1 / 0.75);
        });
      });
      vp.addEventListener('wheel', function (e) {
        e.preventDefault(); var p = toSvg(e.clientX, e.clientY); zoom(e.deltaY < 0 ? 0.85 : 1 / 0.85, p.x, p.y);
      }, { passive: false });
      vp.addEventListener('keydown', function (e) {
        var step = view.w * 0.1, k = e.key;
        if (k === 'ArrowLeft') view.x -= step; else if (k === 'ArrowRight') view.x += step;
        else if (k === 'ArrowUp') view.y -= step; else if (k === 'ArrowDown') view.y += step;
        else if (k === '+' || k === '=') { zoom(0.8); e.preventDefault(); return; }
        else if (k === '-' || k === '_') { zoom(1.25); e.preventDefault(); return; }
        else if (k === '0') { fit(); e.preventDefault(); return; }
        else return;
        e.preventDefault(); set();
      });
      var pointers = {}, last = null, pinch = null, moved = false;
      vp.addEventListener('pointerdown', function (e) {
        pointers[e.pointerId] = { x: e.clientX, y: e.clientY }; moved = false;
        var ids = Object.keys(pointers);
        if (ids.length === 2) { var a = pointers[ids[0]], b = pointers[ids[1]]; pinch = Math.hypot(a.x - b.x, a.y - b.y); last = null; }
        else last = { x: e.clientX, y: e.clientY };
      });
      vp.addEventListener('pointermove', function (e) {
        if (!pointers[e.pointerId]) return;
        pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
        var ids = Object.keys(pointers);
        if (ids.length === 2 && pinch) {
          var a = pointers[ids[0]], b = pointers[ids[1]], d = Math.hypot(a.x - b.x, a.y - b.y);
          var c = toSvg((a.x + b.x) / 2, (a.y + b.y) / 2); zoom(pinch / d, c.x, c.y); pinch = d; moved = true; return;
        }
        if (!last) return;
        var r = svg.getBoundingClientRect(), dx = e.clientX - last.x, dy = e.clientY - last.y;
        if (Math.abs(dx) + Math.abs(dy) > 3) { moved = true; vp.setPointerCapture(e.pointerId); }
        view.x -= dx / r.width * view.w; view.y -= dy / r.height * view.h; last = { x: e.clientX, y: e.clientY }; set();
      });
      function up(e) { delete pointers[e.pointerId]; if (Object.keys(pointers).length < 2) pinch = null; last = null; }
      vp.addEventListener('pointerup', up); vp.addEventListener('pointercancel', up);
      vp.addEventListener('click', function (e) { if (moved) { e.preventDefault(); moved = false; } }, true);   // a drag is not a click
      fit();
      window.addEventListener('resize', fit);
    });
  });
})();
