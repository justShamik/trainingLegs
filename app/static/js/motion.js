/* motion.js - Apple-style scroll choreography for the Running Coach UI.
 *
 *  - Adds .js-motion to <html> (CSS only hides reveal targets under that class,
 *    so if this file fails to load nothing is ever stuck invisible).
 *  - [data-reveal] / .section-reveal       fade + rise in when scrolled into view
 *      data-reveal="fade|scale|left|right"   variants (default: up)
 *      data-reveal-delay="120"               extra delay in ms
 *  - [data-reveal-stagger]                  reveals its direct children one after another
 *      data-reveal-stagger="70"              step in ms (default 70)
 *  - [data-parallax="0.25"]                 hero drifts + fades as the page scrolls
 *  - .dial[data-pct]                        SVG ring injected, fill animates on reveal
 *  - .navbar                                gets .is-condensed once the page is scrolled
 *  - Auto-reveal: cards, charts, tables and section headings inside <main> are
 *    revealed automatically unless they (or an ancestor) opt out with data-reveal="none".
 *
 * prefers-reduced-motion: no hidden states, no parallax, dials drawn at their final value.
 * Only transform/opacity are animated. Public API: window.Motion.{refresh, hydrateDial, reveal}.
 */
(function () {
  'use strict';

  var doc = document.documentElement;
  var reduced = false;
  try { reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) {}
  var canObserve = 'IntersectionObserver' in window;

  var AUTO_SELECTOR = [
    'main .card', 'main .chart-card', 'main .kpi-card', 'main .kpi', 'main .table-container',
    'main .section-head', 'main > h2', 'main .callout', 'main .week-toggle', 'main .dial'
  ].join(',');
  var SVG_NS = 'http://www.w3.org/2000/svg';

  function clampPct(v) {
    var n = parseFloat(v);
    if (isNaN(n)) return 0;
    return Math.max(0, Math.min(100, n));
  }

  /* ---------------------------------------------------------------- dials */
  function hydrateDial(el) {
    if (!el || el.classList.contains('is-hydrated')) return el;
    var pct = clampPct(el.getAttribute('data-pct') != null ? el.getAttribute('data-pct')
      : getComputedStyle(el).getPropertyValue('--pct'));
    el.style.setProperty('--pct', pct);

    var svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('class', 'dial__svg');
    svg.setAttribute('viewBox', '0 0 120 120');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    ['dial__track', 'dial__fill'].forEach(function (cls) {
      var c = document.createElementNS(SVG_NS, 'circle');
      c.setAttribute('class', cls);
      c.setAttribute('cx', '60');
      c.setAttribute('cy', '60');
      c.setAttribute('r', '53');
      c.setAttribute('pathLength', '100');
      svg.appendChild(c);
    });

    // Wrap loose value/label children in a centred stack.
    var center = el.querySelector('.dial__center');
    if (!center) {
      center = document.createElement('div');
      center.className = 'dial__center';
      while (el.firstChild) center.appendChild(el.firstChild);
      el.appendChild(center);
    }
    el.insertBefore(svg, el.firstChild);
    el.classList.add('is-hydrated');
    if (!el.hasAttribute('role')) {
      el.setAttribute('role', 'img');
      if (!el.hasAttribute('aria-label')) {
        el.setAttribute('aria-label', (center.textContent || '').replace(/\s+/g, ' ').trim() + ' (' + Math.round(pct) + '%)');
      }
    }
    return el;
  }

  /* --------------------------------------------------------------- reveal */
  var observer = null;

  function reveal(el) {
    if (el.classList.contains('is-in')) return;
    el.classList.add('is-in');
    var dials = el.classList.contains('dial') ? [el] : el.querySelectorAll('.dial');
    for (var i = 0; i < dials.length; i++) dials[i].classList.add('is-in');
    // drop will-change once the transition has settled
    setTimeout(function () { el.classList.add('is-done'); }, 1600);
  }

  function onIntersect(entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      var el = entry.target;
      observer.unobserve(el);
      if (el.hasAttribute('data-reveal-stagger')) {
        var step = parseInt(el.getAttribute('data-reveal-stagger'), 10) || 70;
        var kids = el.children;
        for (var i = 0; i < kids.length; i++) {
          kids[i].style.setProperty('--reveal-delay', Math.min(i * step, 600) + 'ms');
          reveal(kids[i]);
        }
      }
      reveal(el);
    });
  }

  function prepare(el) {
    if (el.__motion) return;
    el.__motion = true;
    var d = el.getAttribute('data-reveal-delay');
    if (d) el.style.setProperty('--reveal-delay', parseInt(d, 10) + 'ms');
    if (observer) observer.observe(el); else reveal(el);
  }

  function collect(root) {
    root = root || document;
    var main = document.querySelector('main');
    if (main) {
      var auto = main.querySelectorAll(AUTO_SELECTOR);
      for (var i = 0; i < auto.length; i++) {
        var el = auto[i];
        if (el.hasAttribute('data-reveal') || el.classList.contains('section-reveal')) continue;
        // skip if an ancestor already reveals (avoids double fades) or opted out
        var p = el.parentElement, skip = false;
        while (p && p !== main) {
          if (p.hasAttribute('data-reveal') || p.classList.contains('section-reveal') ||
              p.hasAttribute('data-reveal-stagger')) { skip = true; break; }
          p = p.parentElement;
        }
        if (!skip && !el.closest('.page-hero')) el.setAttribute('data-reveal', '');
      }
    }
    // stagger parents mark their children as reveal targets
    var groups = root.querySelectorAll('[data-reveal-stagger]');
    for (var g = 0; g < groups.length; g++) {
      for (var k = 0; k < groups[g].children.length; k++) {
        var child = groups[g].children[k];
        if (!child.hasAttribute('data-reveal')) child.setAttribute('data-reveal', '');
        child.__motion = true; // revealed by the parent
      }
      prepare(groups[g]);
    }
    var targets = root.querySelectorAll('[data-reveal]:not([data-reveal="none"]), .section-reveal');
    for (var t = 0; t < targets.length; t++) prepare(targets[t]);
    var opt = root.querySelectorAll('[data-reveal="none"]');
    for (var o = 0; o < opt.length; o++) opt[o].classList.add('is-in');
  }

  /* ----------------------------------------------------- scroll handlers */
  var navbar = null, parallax = [], ticking = false;

  function onScroll() {
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(function () {
      ticking = false;
      var y = window.pageYOffset || doc.scrollTop || 0;
      if (navbar) navbar.classList.toggle('is-condensed', y > 8);
      if (reduced) return;
      for (var i = 0; i < parallax.length; i++) {
        var p = parallax[i];
        var h = p.el.offsetHeight || 1;
        var progress = Math.max(0, Math.min(1, y / (h + 160)));
        p.el.style.setProperty('--parallax-y', (y * p.speed).toFixed(1) + 'px');
        p.el.style.setProperty('--parallax-o', (1 - progress * 0.85).toFixed(3));
      }
    });
  }

  /* ------------------------------------------------------------------ init */
  function init() {
    navbar = document.querySelector('.navbar');

    var dials = document.querySelectorAll('.dial');
    for (var i = 0; i < dials.length; i++) hydrateDial(dials[i]);

    if (!reduced) {
      var ps = document.querySelectorAll('[data-parallax]');
      for (var j = 0; j < ps.length; j++) {
        parallax.push({ el: ps[j], speed: parseFloat(ps[j].getAttribute('data-parallax')) || 0.25 });
      }
    }

    if (reduced || !canObserve) {
      // everything visible, dials at final value
      var all = document.querySelectorAll('[data-reveal], .section-reveal, .dial');
      for (var k = 0; k < all.length; k++) all[k].classList.add('is-in');
    } else {
      observer = new IntersectionObserver(onIntersect, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
      doc.classList.add('js-motion');
      // let the browser commit the hidden state before observing, so in-view items animate in
      collect(document);
    }

    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  window.Motion = {
    refresh: function (root) { if (observer) collect(root || document); },
    hydrateDial: hydrateDial,
    reveal: reveal,
    setDial: function (el, pct) {
      hydrateDial(el);
      el.setAttribute('data-pct', clampPct(pct));
      el.style.setProperty('--pct', clampPct(pct));
    }
  };

  function safeInit() {
    try { init(); } catch (err) {
      // never leave content hidden
      doc.classList.remove('js-motion');
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', safeInit);
  else safeInit();
})();
