// Oral history pages: transcript timestamps jump the player to that moment, and the transcript can
// be searched. Without JavaScript the timestamps are plain links and the full transcript is shown.
(function () {
  'use strict';
  document.addEventListener('DOMContentLoaded', function () {
    var player = document.getElementById('oh-player'), tr = document.getElementById('transcript');
    if (!tr) return;
    tr.addEventListener('click', function (e) {
      var a = e.target.closest('[data-seek]');
      if (!a || !player) return;
      e.preventDefault();
      player.currentTime = +a.getAttribute('data-seek');
      player.play();
      player.focus();
    });
    var box = document.querySelector('.transcript-search'), q = document.getElementById('ts-q'), count = document.getElementById('ts-count');
    if (!box || !q) return;
    box.hidden = false;
    var lines = Array.prototype.slice.call(tr.querySelectorAll('.transcript__line'));
    var norm = function (s) { return s.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase(); };
    q.addEventListener('input', function () {
      var term = norm(q.value.trim()), n = 0;
      lines.forEach(function (l) {
        var hit = term && norm(l.textContent).indexOf(term) >= 0;
        l.classList.toggle('transcript__line--hit', !!hit);
        l.classList.toggle('transcript__line--dim', !!term && !hit);
        if (hit) n += 1;
      });
      count.textContent = term ? ' ' + n : '';
      var first = tr.querySelector('.transcript__line--hit');
      if (first) first.scrollIntoView({ block: 'nearest' });
    });
  });
})();
