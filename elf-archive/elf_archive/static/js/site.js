// Progressive enhancement only. Every page works without JavaScript.
document.documentElement.classList.add('js');
document.addEventListener('DOMContentLoaded', function () {
  // Compact navigation toggle on small screens.
  var btn = document.getElementById('nav-toggle'), wrap = document.getElementById('nav-wrap');
  if (btn && wrap) {
    btn.addEventListener('click', function () {
      var open = wrap.classList.toggle('open');
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }
  // Warn before leaving a contribution form with unsaved changes.
  document.querySelectorAll('form[data-warn-unsaved]').forEach(function (form) {
    var dirty = false;
    form.addEventListener('input', function () { dirty = true; });
    form.addEventListener('submit', function () { dirty = false; });
    window.addEventListener('beforeunload', function (e) { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
  });
  // Ask for confirmation on irreversible editorial actions.
  document.querySelectorAll('[data-confirm]').forEach(function (el) {
    el.addEventListener('click', function (e) { if (!window.confirm(el.getAttribute('data-confirm'))) e.preventDefault(); });
  });
  // Type-to-search for references to other records: refresh the suggestion list as the user types.
  document.querySelectorAll('input[data-lookup]').forEach(function (input) {
    var list = document.getElementById(input.getAttribute('list')), timer = null, last = '';
    if (!list || !window.fetch) return;
    input.addEventListener('input', function () {
      var q = input.value.trim();
      if (q === last || /\[[a-z]{3}-[a-z0-9]{8}\]$/.test(q)) return;   // a full choice was made
      last = q;
      clearTimeout(timer);
      if (q.length < 1) return;
      timer = setTimeout(function () {
        fetch('/lookup/' + encodeURIComponent(input.getAttribute('data-lookup')) + '?q=' + encodeURIComponent(q),
              { headers: { 'Accept': 'application/json' } })
          .then(function (r) { return r.ok ? r.json() : []; })
          .then(function (items) {
            list.innerHTML = '';
            items.forEach(function (it) { var o = document.createElement('option'); o.value = it.label; list.appendChild(o); });
          }).catch(function () { /* keep the existing suggestions */ });
      }, 200);
    });
  });
  // "Related records" lists: a search box that adds the chosen record as a new line.
  document.querySelectorAll('input[data-refs-add]').forEach(function (input) {
    var target = document.getElementById(input.getAttribute('data-refs-add'));
    if (!target) return;
    input.closest('.refs-adder').hidden = false;
    function add() {
      var v = input.value.trim();
      if (!/\[[a-z]{3}-[a-z0-9]{8}\]$/.test(v)) return false;
      target.value = (target.value.trim() ? target.value.trim() + '\n' : '') + v;
      input.value = '';
      target.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    }
    input.addEventListener('change', add);
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); add(); } });
  });
  // Photo uploads: show progress. Without JavaScript the form still posts normally.
  document.querySelectorAll('form[data-upload]').forEach(function (form) {
    var box = form.querySelector('.upload-progress'), bar = box && box.querySelector('progress'),
        label = box && box.querySelector('span'), btn = form.querySelector('button[type=submit]');
    if (!box || !window.FormData || !window.XMLHttpRequest) return;
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      form.querySelectorAll('.js-upload-error').forEach(function (n) { n.remove(); });
      var xhr = new XMLHttpRequest(), original = btn.textContent;
      xhr.open('POST', form.action);
      xhr.setRequestHeader('X-Upload-Progress', '1');
      xhr.upload.addEventListener('progress', function (ev) {
        if (ev.lengthComputable) { var pct = Math.round(ev.loaded / ev.total * 100); bar.value = pct; label.textContent = pct + '%'; }
      });
      xhr.addEventListener('load', function () {
        var data = null;
        try { data = JSON.parse(xhr.responseText); } catch (err) { /* not JSON, e.g. a size-limit page */ }
        if (xhr.status === 200 && data && data.redirect) {
          var target = new URL(data.redirect, window.location.href);
          if (target.pathname === window.location.pathname && target.search === window.location.search) {
            window.location.hash = target.hash;    // same page: a hash change alone would not reload it
            window.location.reload();
          } else {
            window.location.assign(target.href);
          }
          return;
        }
        box.hidden = true; btn.disabled = false; btn.textContent = original;
        var errors = (data && data.errors) || { photo: xhr.status === 413 ? form.getAttribute('data-too-large') : form.getAttribute('data-failed') };
        Object.keys(errors).forEach(function (name) {
          var field = form.querySelector('[name="' + name + '"]'), holder = field ? (field.closest('.field') || field.closest('.check')) : form;
          var msg = document.createElement('div');
          msg.className = 'error-text js-upload-error'; msg.setAttribute('role', 'alert'); msg.textContent = errors[name];
          (holder || form).appendChild(msg);
        });
        var first = form.querySelector('.js-upload-error');
        if (first) first.scrollIntoView({ block: 'center' });
      });
      xhr.addEventListener('error', function () {
        box.hidden = true; btn.disabled = false; btn.textContent = original;
        var msg = document.createElement('div');
        msg.className = 'error-text js-upload-error'; msg.setAttribute('role', 'alert'); msg.textContent = form.getAttribute('data-failed');
        form.appendChild(msg);
      });
      box.hidden = false; bar.value = 0; label.textContent = '0%';
      btn.disabled = true; btn.textContent = btn.getAttribute('data-uploading') || original;
      xhr.send(new FormData(form));
    });
  });
  // Shown inside another site (the embedded map and timeline): links to records and other pages open in a new tab,
  // so a visitor never ends up browsing the whole archive inside a small frame.
  if (document.body.hasAttribute('data-embed')) {
    document.addEventListener('click', function (e) {
      var a = e.target.closest && e.target.closest('a[href]');
      if (!a || a.getAttribute('href').charAt(0) === '#' || a.closest('#ex-modes')) return;
      a.target = '_blank'; a.rel = 'noopener';
    });
  }
  // Move focus to the error summary when a form comes back with errors.
  var summary = document.getElementById('error-summary');
  if (summary) summary.focus();
});
