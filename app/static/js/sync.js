/* sync.js - shared behaviour for long-running POST forms (COROS sync, race refresh).
 *
 *  form.sync-form[data-message][data-title]  shows #syncOverlay while the POST is in flight,
 *                                            highlights its .sync-btn (.is-syncing) and disables
 *                                            every .sync-btn once the submit has been dispatched.
 *  [data-utc]                                ISO-8601 UTC timestamps rewritten in the browser's
 *                                            timezone (data-format="date" for the date only).
 *  Back/forward cache: the overlay is never left stuck; buttons the server rendered disabled
 *  (data-locked) stay disabled.
 */
(function () {
  'use strict';

  function localise(root) {
    var els = (root || document).querySelectorAll('[data-utc]');
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      var d = new Date(el.getAttribute('data-utc'));
      if (isNaN(d)) continue;
      var opts = el.getAttribute('data-format') === 'date'
        ? { dateStyle: 'medium' } : { dateStyle: 'medium', timeStyle: 'short' };
      el.textContent = d.toLocaleString(undefined, opts);
      try { el.title = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch (e) {}
    }
  }

  function overlayParts() {
    return {
      overlay: document.getElementById('syncOverlay'),
      title: document.getElementById('syncOverlayTitle'),
      msg: document.getElementById('syncOverlayMsg')
    };
  }

  function resetButtons() {
    var p = overlayParts();
    if (p.overlay) p.overlay.style.display = 'none';
    if (p.title && p.title.dataset.default) p.title.textContent = p.title.dataset.default;
    var btns = document.querySelectorAll('.sync-btn');
    for (var i = 0; i < btns.length; i++) {
      btns[i].classList.remove('is-syncing');
      if (!btns[i].hasAttribute('data-locked')) btns[i].disabled = false;
    }
  }

  function init() {
    localise(document);
    var forms = document.querySelectorAll('form.sync-form');
    for (var i = 0; i < forms.length; i++) {
      forms[i].addEventListener('submit', function (ev) {
        var form = ev.currentTarget;
        var btn = form.querySelector('.sync-btn');
        if (btn) btn.classList.add('is-syncing');
        var p = overlayParts();
        if (p.title) p.title.textContent = form.dataset.title || p.title.dataset.default || p.title.textContent;
        if (p.msg) p.msg.textContent = form.dataset.message || '';
        if (p.overlay) p.overlay.style.display = 'flex';
        // Disable after the submit has been dispatched so the POST still goes out
        setTimeout(function () {
          var all = document.querySelectorAll('.sync-btn');
          for (var j = 0; j < all.length; j++) all[j].disabled = true;
        }, 0);
      });
    }
    window.addEventListener('pageshow', resetButtons);
  }

  window.CoachSync = { localise: localise, reset: resetButtons };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
