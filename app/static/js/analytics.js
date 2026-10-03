/* Privacy-first self-hosted analytics. No cookies, no IP, no form values. Fails silently. */
(function () {
  'use strict';
  try {
    var LS = 'analytics_optout', SS = 'analytics_sid';
    var qs = new URLSearchParams(location.search).get('analytics');
    try {
      if (qs === 'off') localStorage.setItem(LS, '1');
      if (qs === 'on') localStorage.removeItem(LS);
    } catch (e) {}
    window.analyticsOptedOut = function () {
      try { if (localStorage.getItem(LS) === '1') return true; } catch (e) {}
      return navigator.doNotTrack === '1' || window.doNotTrack === '1';
    };
    window.analyticsSetOptOut = function (off) {
      try { off ? localStorage.setItem(LS, '1') : localStorage.removeItem(LS); } catch (e) {}
    };
    if (window.analyticsOptedOut()) return;
    if (location.pathname.indexOf('/analytics') === 0) return; // never measure the dashboard itself

    var sid;
    try {
      sid = sessionStorage.getItem(SS);
      if (!sid) {
        sid = 's' + Math.random().toString(36).slice(2, 12) + Date.now().toString(36);
        sessionStorage.setItem(SS, sid);
      }
    } catch (e) { sid = 'snostore' + Math.random().toString(36).slice(2, 10); }

    var ENDPOINT = '/analytics/event';
    function send(type, target, props, dur) {
      try {
        var body = JSON.stringify({ sid: sid, type: type, page: location.pathname,
          target: target ? String(target).slice(0, 40) : null, props: props || null,
          duration_ms: dur == null ? null : dur });
        if (navigator.sendBeacon) {
          navigator.sendBeacon(ENDPOINT, new Blob([body], { type: 'text/plain' }));
        } else if (window.fetch) {
          fetch(ENDPOINT, { method: 'POST', body: body, keepalive: true,
            headers: { 'Content-Type': 'text/plain' } }).catch(function () {});
        }
      } catch (e) {}
    }

    window.addEventListener('load', function () {
      setTimeout(function () {
        try {
          var nav = performance.getEntriesByType('navigation')[0];
          var ms = nav ? nav.loadEventEnd : (performance.timing.loadEventEnd - performance.timing.navigationStart);
          if (ms > 0) send('page_load_ms', null, null, Math.round(ms));
        } catch (e) {}
      }, 0);
    });

    document.addEventListener('click', function (ev) {
      try {
        var el = ev.target && ev.target.closest ? ev.target.closest('[data-track],button,a') : null;
        if (!el) return;
        var label = el.getAttribute('data-track') || el.id ||
          (el.textContent || '').replace(/\s+/g, ' ').trim();
        send('click', label, { tag: el.tagName.toLowerCase() });
      } catch (e) {}
    }, true);

    document.addEventListener('submit', function (ev) {
      try {
        var f = ev.target;
        send('form_submit', f.getAttribute('data-track') || f.id || f.getAttribute('action') || 'form');
      } catch (e) {}
    }, true);

    window.addEventListener('error', function (ev) {
      var m = String(ev.message || 'error');
      send('error', m.slice(0, 40), { message: m.slice(0, 80) });
    });
    window.addEventListener('unhandledrejection', function (ev) {
      var m = ev.reason && ev.reason.message ? ev.reason.message : String(ev.reason || 'rejection');
      send('error', m.slice(0, 40), { message: m.slice(0, 80) });
    });

    var t0 = Date.now(), sent = false;
    function leave() {
      if (sent) return;
      sent = true;
      send('time_on_page', null, null, Date.now() - t0);
    }
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'hidden') leave(); else { sent = false; t0 = Date.now(); }
    });
    window.addEventListener('pagehide', leave);
  } catch (e) { /* never throw */ }
})();
