# Design system

Sharp near-black base, one crisp signal-orange accent used sparingly (primary buttons, active nav,
key numbers), and a soft pastel palette for data (KPI tiles, chart series, chips, dials).
Everything lives in `app/static/css/style.css`; scroll choreography in `app/static/js/motion.js`;
chart defaults in `app/static/js/charts.js`.

Screenshots: `docs/screenshots/redesign/` (`<page>-<desktop|phone>[-hero].png`).

## Tokens (`:root`)

| Group | Tokens |
|---|---|
| Surfaces | `--bg-primary #060708`, `--bg-surface #0e1013`, `--bg-surface-elevated #16191e`, `--bg-surface-hover`, `--bg-glass`, `--border-color`, `--border-highlight`, `--hairline` |
| Text | `--text-primary #f5f5f7`, `--text-secondary #b3b3ba`, `--text-muted #8b8b93` (all AA on the surfaces), `--text-on-accent #0a0a0b` |
| Accent | `--accent-orange #ff5c1a`, `--accent-orange-hover`, `--accent-orange-press`, `--accent-soft` (14% tint), `--accent-glow` |
| Pastels | `--pastel-peach #ffb89a`, `--pastel-apricot #ffd09c`, `--pastel-butter #f5e09a`, `--pastel-mint #9fe3c4`, `--pastel-sky #a6d0f5`, `--pastel-lavender #c6b6f7`, `--pastel-rose #f7a6b7` |
| Status | `--status-success` (mint), `--status-warning` (butter), `--status-danger` / `--status-error` (rose), `--status-info` (sky) |
| Type | `--font-serif` Instrument Serif (h1 / display), `--font-display` Inter Tight (headings, numbers), `--font-body` Inter |
| Space | `--space-xs 4` `sm 8` `md 16` `lg 24` `xl 32` `2xl 48` `3xl 80`, `--gutter` (32 / 20 / 16 px) |
| Radius | `--radius-sm 10` `md 16` `lg 22` `xl 28` `pill` |
| Elevation | `--shadow-card`, `--shadow-pop` |
| Motion | `--ease-out cubic-bezier(.22,1,.36,1)`, `--ease-in-out`, `--ease-spring`, `--dur-fast 180ms`, `--dur-base 320ms`, `--dur-reveal 900ms` |

Legacy token names (`--accent-orange`, `--bg-surface-elevated`, `--font-display`, ...) are kept so old inline styles keep working.

Rules of tone: sentence case everywhere. Uppercase + wide tracking only for `.eyebrow` labels.
Use `.num` / tabular numerals for metrics. Orange is for action and the single most important number - not decoration.

## Typography helpers

- `h1` - Instrument Serif, fluid 40-72px. `h2` - Inter Tight 600, tight tracking. `h3` - 500 weight.
- `.eyebrow` (`--accent` variant, `--plain` without dot) - small uppercase label above headings.
- `.lead` - large secondary intro paragraph.
- `.sc` - shows a legacy ALL-CAPS DOM string in sentence case (`text-transform` only; DOM text unchanged, tests rely on it). Wrap acronyms in `.keep-case`.
- `.serif`, `.serif-italic`, `.num`, `.text-secondary`, `.text-muted`, `.text-accent`.

## Layout

- `.page-hero` > `.page-hero__text` (eyebrow, h1, lead, `.page-hero__meta`) + `.page-hero__actions`. Children rise in via CSS keyframes (no JS needed). Add `data-parallax="0.12"` on the hero for the drift/fade on scroll.
- `.section` (80px top spacing) with `.section-head` (eyebrow + h2 on the left, controls on the right).
- `.stack`, `.stack-lg`, `.row`, `.row-between`, `.grid-auto`, `.kpi-grid`, `.charts-grid`, `.form-grid`.

## Components

| Component | Classes |
|---|---|
| Card | `.card` (+ `--interactive`, `--flush`, `--elevated`, `--center`, `--narrow`) |
| Pastel tone | `.tone-peach / apricot / butter / mint / sky / lavender / rose / orange` - sets `--tone`; on a card it adds a soft corner glow, a coloured dot before the label and tints `.card-unit` |
| KPI tile | `.card` + `.card-header` / `.card-value` / `.card-unit` / `.card-subtext` (or `.kpi-card` + `.kpi-label` / `.kpi-value` / `.kpi-subtitle`, or `.kpi` + `.kpi__label/__value/__unit/__sub`). `.kpi--with-dial` puts a `.kpi__body` next to a dial |
| Buttons | `.btn` + `.btn-primary` / `.btn-secondary` / `.btn-ghost` / `.btn-danger` / `.btn-success`; sizes `.btn-sm` / `.btn-lg`; selected state `.is-selected` or `aria-pressed="true"` |
| Links | `.link-arrow` (with `<span class="arrow">&rarr;</span>`), `.back-link` |
| Segmented control | `.segmented` > `.segmented__label` + `a.segmented__item.is-active` |
| Chips | `.chip` + `--orange / --peach / --apricot / --butter / --mint / --sky / --lavender / --rose / --neutral`, semantic aliases `--success / --warning / --danger / --info`; `.chip--lg`; `.chip--raw` keeps original casing (chips otherwise render sentence case). `.badge-na` = dashed neutral "Not Available" badge |
| Callout | `.callout` + `--success / --warning / --danger / --accent`, `.callout__title` |
| Status pill | `.status-pill--ok / --off` + `.status-dot` (navbar COROS state) |
| Tables | `.table-container` > `table.data-table`; `td.empty` for empty rows |
| Forms | `.field` (label + input/select/textarea auto-styled), `.input`, `.form-section` + `.form-section__title` / `__index`, `.panel` |
| Disclosure | `details.disclosure` (+ `--panel`) > `summary` + `.disclosure__body` |
| Progress bar | `.bar` > `.bar__fill` (width inline, colour via `--tone`); fills grow when the parent is revealed |
| Chart card | `.chart-card` > `.chart-title h3` + `.chart-canvas` (260px tall) |
| Misc | `.sync-overlay`, `.sync-spinner`, `.week-toggle`, `.session-card` / `.session-grid`, `.exercise-grid`, `.note`, `.chat-*`, `.msg-*` |

## Motion (`motion.js`, loaded `defer` from `base.html`)

motion.js adds `.js-motion` to `<html>`. Hidden "before reveal" states exist **only** under that class, so if JS fails nothing is stuck invisible. Only `transform` and `opacity` animate.

| Hook | Effect |
|---|---|
| `data-reveal` (or class `.section-reveal`) | fade + rise 28px + slight scale when scrolled into view (IntersectionObserver, once) |
| `data-reveal="fade" / "scale" / "left" / "right"` | variants |
| `data-reveal-delay="120"` | extra delay in ms |
| `data-reveal-stagger="70"` on a parent | children reveal one after another (step ms, capped at 600ms) |
| `data-reveal="none"` | opt an element out of auto-reveal |
| auto-reveal | `main .card, .chart-card, .kpi-card, .kpi, .table-container, .section-head, .callout, .week-toggle, .dial, main > h2` are revealed automatically unless an ancestor already reveals, or they sit in `.page-hero` |
| `data-parallax="0.12"` | element drifts at that fraction of scroll and fades out as it leaves (sets `--parallax-y`, `--parallax-o`) |
| `.navbar` | glass bar (backdrop blur); gets `.is-condensed` after 8px of scroll |
| JS API | `Motion.refresh(root)` after injecting DOM, `Motion.hydrateDial(el)`, `Motion.setDial(el, pct)`, `Motion.reveal(el)` |

`prefers-reduced-motion: reduce`: no hidden states, no parallax, transitions/animations off, dials drawn at their final value; `scroll-behavior: smooth` only when motion is allowed.

## Dial / ring component (for the home page: Sleep, Activity time, Steps, Calories)

```html
<div class="dial-group" data-reveal-stagger="90">
  <div class="dial dial--lg tone-lavender" data-pct="88">
    <span class="dial__value">7h 12<span class="dial__unit">m</span></span>
    <span class="dial__label">Sleep</span>
  </div>
  <div class="dial dial--lg tone-peach" data-pct="64">
    <span class="dial__value">48<span class="dial__unit">min</span></span>
    <span class="dial__label">Activity time</span>
  </div>
  <div class="dial dial--lg tone-mint" data-pct="72">
    <span class="dial__value">7,214</span>
    <span class="dial__label">Steps</span>
  </div>
  <div class="dial dial--lg tone-apricot" data-pct="55">
    <span class="dial__value">1,840</span>
    <span class="dial__label">Calories</span>
  </div>
</div>
```

- `data-pct` 0-100 (clamped) is the fill; compute it server-side against the goal (e.g. sleep minutes / 480 * 100).
- Colour comes from `--tone` (`.tone-*` on the dial or any ancestor; default mint). Suggested mapping: Sleep lavender, Activity time peach, Steps mint, Calories apricot.
- Size: default 132px; `.dial--sm` 92px, `.dial--lg` 180px, or set `--dial-size` / `--dial-stroke` inline.
- motion.js wraps children in `.dial__center`, injects an SVG ring (`.dial__svg` > `.dial__track` + `.dial__fill`, `pathLength=100`), sets `--pct`, adds `role="img"` + an `aria-label` (unless one is given), and animates the fill (`stroke-dashoffset`, 1.6s ease-out) when the dial is revealed.
- Without JS a `conic-gradient` ring rendered from `--pct` is shown: add `style="--pct:72"` too if no-JS fidelity matters.
- Update live: `Motion.setDial(el, 80)`.

## Charts (`charts.js`)

`window.CoachPalette` exposes `orange, peach, apricot, butter, mint, sky, lavender, rose, grid, tick, text, muted`, an ordered `series` array and `alpha(hex, a)`. Global Chart.js defaults: Inter 12px, hairline grid (5% white), no axis borders, circular legend points, rounded bars, dark rounded tooltips, no point dots on lines. Helpers `coachAxis()` / `coachAxisTitle()` / `coachLegend` keep new charts consistent. Load `charts.js` on any page that draws charts.

## Test-safety rules

Keep DOM text that tests assert on (often ALL-CAPS, e.g. `TRAINING DASHBOARD`, `METHODOLOGY:`, `TODAY`) and restyle it with `.sc`; keep ids (`#syncOverlay`, `#syncPendingBtn`, `#lastSyncTime`, `#chatFeed`...), `data-*` attributes, form names/actions and button labels.
