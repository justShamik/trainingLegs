/* scroll-fx.js - GSAP + ScrollTrigger + Lenis scroll choreography, shared by every page.
 *
 * Loaded synchronously from base.html at the end of <body> (after the page's own scripts), so it
 * runs BEFORE the deferred motion.js and can claim the elements it animates: claimed elements get
 * data-reveal="none" (motion.js then marks them .is-in and leaves them alone), stagger parents
 * lose data-reveal-stagger and the hero loses data-parallax. Everything it does not claim is
 * still revealed by motion.js, so unknown content is never stuck invisible.
 *
 * Bails out (motion.js handles the page exactly as before) when GSAP is missing,
 * prefers-reduced-motion is on, or the URL has ?motion=classic.
 *
 * Effects (each one driven by a selector list; pages add to them via PAGES or data attributes):
 *   Lenis       smooth wheel scrolling on the window, driven by gsap.ticker; nested scroll areas
 *               (.chat-feed, textareas, [data-lenis-prevent]) keep native wheel scrolling
 *   hero        .page-hero__text (or [data-fx-hero]): words of the h1 rise in, the rest fades up,
 *               then the block recedes as you scroll away
 *   words       section headings light up word by word (scrubbed)
 *   count       KPI / card / dial numbers count up; the real text stays until the count starts and
 *               is restored exactly at the end; anything that can't round-trip is skipped
 *   batch       cards rise in, in batches, as each row arrives
 *
 * Data-attribute hooks (any template):
 *   data-fx-hero          treat this element as the hero text block
 *   data-fx="words"       heading lights up word by word
 *   data-fx="count"       count this value up
 *   data-fx="batch"       reveal this element with the card batches
 *   data-fx-batch         reveal every direct child with the card batches
 *   data-fx="none"        never touch this element (or anything inside it)
 *
 * Text content is never changed permanently: word splitting keeps textContent identical.
 */
(function () {
  'use strict';

  var gsap = window.gsap, ST = window.ScrollTrigger;
  var reduced = false;
  try { reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) {}
  if (!gsap || !ST || reduced || /[?&]motion=classic\b/.test(location.search)) return;

  var root = document.documentElement;
  var main = document.querySelector('main');
  if (!main) return;

  /* ------------------------------------------------------------------ config */
  var DEFAULTS = {
    hero: '.page-hero > .page-hero__text, [data-fx-hero]',
    heroRecede: { yPercent: -10, scale: 0.94, opacity: 0.12 },
    words: 'main .section-head h2, main > h2, main .card h2, main .form-section__title h2, [data-fx~="words"]',
    count: 'main .card-value, main .kpi-value, main .kpi__value, main .dial__value, [data-fx~="count"]',
    batch: 'main .kpi-grid > *, main .charts-grid > .chart-card, main .race-grid > .card, ' +
           'main .grid-auto > .card, main .stack > .card, main .stack > .panel, ' +
           '[data-fx-batch] > *, [data-fx~="batch"]',
    // cards whose layout must never be transformed by scale (Chart.js canvases measure them)
    noScale: '.chart-card'
  };
  var PAGES = {
    home: {
      heroRecede: { yPercent: -14, scale: 0.9, opacity: 0.08 },
      words: '.race-sub__title'
    },
    plan: {
      // session cards (open weeks) and anything else in the week list reveal in batches;
      // cards inside closed weeks are revealed when their week opens
      batch: 'main .week-body > .card'
    }
  };
  var page = (document.body && document.body.getAttribute('data-fx-page')) || '';
  var cfg = {};
  Object.keys(DEFAULTS).forEach(function (k) { cfg[k] = DEFAULTS[k]; });
  var extra = PAGES[page] || {};
  Object.keys(extra).forEach(function (k) {
    cfg[k] = (typeof extra[k] === 'string' && typeof DEFAULTS[k] === 'string') ? DEFAULTS[k] + ', ' + extra[k] : extra[k];
  });

  gsap.registerPlugin(ST);
  root.classList.add('gsap-fx');
  if (page) root.classList.add('gsap-fx--' + page);

  /* ----------------------------------------------------------------- helpers */
  function all(sel, scope) {
    try { return Array.prototype.slice.call((scope || document).querySelectorAll(sel)); } catch (e) { return []; }
  }
  function optedOut(el) { return !!el.closest('[data-fx~="none"]'); }
  function inHidden(el) { return !!el.closest('[hidden]'); }

  // Wrap every word in spans without changing textContent: whitespace runs stay as text nodes,
  // element children (e.g. <span class="keep-case">) are wrapped whole.
  function splitWords(el, outerClass, innerClass) {
    var out = [];
    function wrap(content) {
      var outer = document.createElement('span');
      outer.className = outerClass;
      var target = outer;
      if (innerClass) {
        target = document.createElement('span');
        target.className = innerClass;
        outer.appendChild(target);
      }
      if (typeof content === 'string') target.textContent = content; else target.appendChild(content);
      if (!out.length) outer.classList.add('split-first');
      out.push(target);
      return outer;
    }
    Array.prototype.slice.call(el.childNodes).forEach(function (node) {
      if (node.nodeType === 3) {
        var frag = document.createDocumentFragment();
        node.nodeValue.split(/(\s+)/).forEach(function (part) {
          if (!part) return;
          frag.appendChild(/^\s+$/.test(part) ? document.createTextNode(part) : wrap(part));
        });
        el.replaceChild(frag, node);
      } else if (node.nodeType === 1) {
        var placeholder = document.createComment('');
        el.replaceChild(placeholder, node);
        el.replaceChild(wrap(node), placeholder);
      }
    });
    return out;
  }

  /* ------------------------------------------------- number parsing for count-up */
  // Returns { node, target, fmt } when the element's single text value can be counted and
  // formatted back to exactly the same string; otherwise null (element is left alone).
  function parseCount(el) {
    var texts = Array.prototype.filter.call(el.childNodes, function (n) {
      return n.nodeType === 3 && /\S/.test(n.nodeValue);
    });
    if (texts.length !== 1) return null;
    var node = texts[0], raw = node.nodeValue;
    var m = /^(\s*)(.*?)(\s*)$/.exec(raw);
    var lead = m[1], core = m[2], trail = m[3];
    var parts = /^(\d+:\d{2}|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(\s?(?:%|\/km|\/mi))?$/.exec(core);
    if (!parts) return null;
    var num = parts[1], suffix = parts[2] || '', target, fmt;
    var clock = /^(\d+):(\d{2})$/.exec(num);
    if (clock) {
      target = +clock[1] * 60 + +clock[2];
      fmt = function (v) { v = Math.round(v); return Math.floor(v / 60) + ':' + ('0' + v % 60).slice(-2); };
    } else {
      var dec = (num.split('.')[1] || '').length, commas = num.indexOf(',') >= 0;
      target = parseFloat(num.replace(/,/g, ''));
      fmt = function (v) {
        var s = v.toFixed(dec);
        if (!commas) return s;
        var p = s.split('.');
        p[0] = p[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
        return p.join('.');
      };
    }
    if (!(target > 0) || fmt(target) !== num) return null;
    return {
      node: node, final: raw, target: target,
      render: function (v) { return lead + fmt(v) + suffix + trail; }
    };
  }

  /* ------------------------------------------------- claim before motion.js runs */
  var claimed = [];
  function claim(el) {
    if (el.getAttribute('data-reveal') !== 'none') el.setAttribute('data-reveal', 'none');
    claimed.push(el);
  }

  // hero
  var heroText = null;
  all(cfg.hero).some(function (el) {
    if (optedOut(el) || inHidden(el)) return false;
    heroText = el;
    return true;
  });
  var hero = heroText && (heroText.closest('.page-hero') || heroText);
  if (hero) {
    hero.removeAttribute('data-parallax');
    if (hero === heroText) claim(heroText);
  }

  // headings (and the section-head around them, so it doesn't fade separately)
  var headings = all(cfg.words).filter(function (h) {
    return !optedOut(h) && !(hero && hero.contains(h)) && !h.querySelector('h1, h2, h3, p, div');
  });
  headings.forEach(function (h) {
    var head = h.closest('.section-head');
    if (head) claim(head);
    else if (h.parentElement === main) claim(h);
  });

  // card batches
  var cards = all(cfg.batch).filter(function (c, i, arr) {
    return arr.indexOf(c) === i && !optedOut(c) && !(hero && hero.contains(c));
  });
  // a card nested in another batched card is revealed with its parent
  cards = cards.filter(function (c) {
    return !cards.some(function (o) { return o !== c && o.contains(c); });
  });
  cards.forEach(function (c) {
    if (c.parentElement && c.parentElement.hasAttribute('data-reveal-stagger')) c.parentElement.removeAttribute('data-reveal-stagger');
    // a hidden stagger parent would otherwise hide every child; make sure the parent itself shows
    if (c.parentElement && c.parentElement.hasAttribute('data-reveal') && c.parentElement !== main) claim(c.parentElement);
    claim(c);
  });

  /* ------------------------------------------------- Lenis smooth scrolling */
  var lenis = null;
  all('.chat-feed, textarea').forEach(function (el) { el.setAttribute('data-lenis-prevent', ''); });
  if (window.Lenis) {
    var nav = document.querySelector('.navbar');
    lenis = new window.Lenis({
      lerp: 0.1, smoothWheel: true,
      anchors: { offset: -((nav ? nav.offsetHeight : 64) + 16) }
    });
    lenis.on('scroll', function () { ST.update(); onScrollEnd(); });
    gsap.ticker.add(function (time) { lenis.raf(time * 1000); });
    gsap.ticker.lagSmoothing(0);
    // freeze the page behind the sync overlay; resume when the page comes back (bfcache)
    document.addEventListener('submit', function (ev) {
      if (ev.target && ev.target.classList && ev.target.classList.contains('sync-form') && !ev.defaultPrevented) lenis.stop();
    });
    window.addEventListener('pageshow', function () { lenis.start(); });
  } else {
    window.addEventListener('scroll', onScrollEnd, { passive: true });
  }

  /* ------------------------------------------------- hero */
  if (heroText) {
    var kids = Array.prototype.slice.call(heroText.children);
    var title = heroText.querySelector('h1');
    var words = title ? splitWords(title, 'split-word', 'split-inner') : [];
    var rest = kids.filter(function (k) { return k !== title; });
    var tl = gsap.timeline({ defaults: { ease: 'expo.out' } });
    var before = title ? rest.slice(0, kids.indexOf(title)) : [];
    var after = title ? rest.slice(kids.indexOf(title)) : rest;
    if (before.length) tl.from(before, { y: 16, opacity: 0, duration: 0.9, stagger: 0.06 }, 0);
    if (words.length) tl.from(words, { yPercent: 115, duration: 1.3, stagger: 0.09 }, 0.1);
    if (after.length) tl.from(after, { y: 22, opacity: 0, duration: 1.1, stagger: 0.08, clearProps: 'transform,opacity' }, 0.4);

    gsap.to(heroText, {
      yPercent: cfg.heroRecede.yPercent, scale: cfg.heroRecede.scale, opacity: cfg.heroRecede.opacity, ease: 'none',
      scrollTrigger: {
        trigger: hero, start: 0, scrub: true, invalidateOnRefresh: true,
        end: function () { return Math.max(1, hero.offsetTop + hero.offsetHeight); }
      }
    });
  }

  /* ------------------------------------------------- headings light up word by word */
  headings.forEach(function (h) {
    var w = splitWords(h, 'scrub-word');
    if (!w.length) return;
    gsap.fromTo(w, { opacity: 0.16 }, {
      opacity: 1, stagger: 0.15, ease: 'none',
      // clamp() on the end: headings near the page bottom still reach full brightness
      scrollTrigger: { trigger: h, start: 'top 90%', end: 'clamp(top 58%)', scrub: 0.6 }
    });
  });

  /* ------------------------------------------------- count-up numbers */
  all(cfg.count).forEach(function (el) {
    if (optedOut(el) || inHidden(el)) return;
    var c = parseCount(el);
    if (!c) return;
    var state = { v: 0 };
    gsap.to(state, {
      v: 1, duration: 1.6, ease: 'power3.out',
      scrollTrigger: { trigger: el, start: 'top 96%', once: true },
      onStart: function () { c.node.nodeValue = c.render(0); },
      onUpdate: function () { c.node.nodeValue = c.render(state.v * c.target); },
      onComplete: function () { c.node.nodeValue = c.final; }
    });
  });

  /* ------------------------------------------------- card batches */
  var pending = [];
  function revealCards(batch, fast) {
    batch = batch.filter(function (el) { return pending.indexOf(el) >= 0; });
    if (!batch.length) return;
    batch.forEach(function (el) {
      pending.splice(pending.indexOf(el), 1);
      all('.dial', el).forEach(function (d) { d.classList.add('is-in'); });
    });
    gsap.to(batch, {
      y: 0, opacity: 1, scale: 1, duration: fast ? 0.7 : 1.1, ease: 'expo.out', stagger: fast ? 0.05 : 0.09,
      overwrite: true, clearProps: 'transform,opacity',
      onComplete: function () { batch.forEach(function (el) { el.classList.remove('fx-pending'); }); }
    });
  }
  if (cards.length) {
    cards.forEach(function (c) {
      c.classList.add('fx-pending');
      gsap.set(c, c.matches(cfg.noScale) ? { y: 48, opacity: 0 } : { y: 60, opacity: 0, scale: 0.97 });
      pending.push(c);
    });
    var visibleCards = cards.filter(function (c) { return !inHidden(c); });
    if (visibleCards.length) {
      ST.batch(visibleCards, {
        start: 'top 96%', once: true,
        onEnter: function (batch) { revealCards(batch); }
      });
    }
  }

  // safety net: once the page is scrolled to the bottom, nothing may remain hidden
  function onScrollEnd() {
    if (!pending.length) return;
    var doc = document.scrollingElement || root;
    if (window.innerHeight + (window.pageYOffset || doc.scrollTop) >= doc.scrollHeight - 4) {
      revealCards(pending.filter(function (el) { return !inHidden(el); }), true);
    }
  }

  // sections opened later (plan week toggles, [hidden] panels): reveal their cards, re-measure
  var refreshTimer = null;
  function refreshSoon() {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(function () { ST.refresh(); }, 80);
  }
  if ('MutationObserver' in window) {
    new MutationObserver(function (records) {
      var opened = false;
      records.forEach(function (r) {
        if (r.type === 'attributes' && !r.target.hasAttribute('hidden')) opened = true;
      });
      if (opened) {
        revealCards(pending.filter(function (el) { return !inHidden(el); }), true);
      }
      refreshSoon();
    }).observe(main, { attributes: true, attributeFilter: ['hidden', 'open'], subtree: true });
  }
  // layout changes (charts rendering, <details> toggles, chat messages, fonts) -> re-measure
  if ('ResizeObserver' in window) {
    var lastH = 0;
    new ResizeObserver(function () {
      var h = document.body.scrollHeight;
      if (Math.abs(h - lastH) > 2) { lastH = h; refreshSoon(); }
    }).observe(document.body);
  }
  window.addEventListener('load', function () { ST.refresh(); });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { ST.refresh(); });

  window.ScrollFx = { lenis: lenis, refresh: function () { ST.refresh(); }, page: page };
})();
