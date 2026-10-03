# Race research: watchlist and NCR 50 km races (as of 2026-10-03)

Seed data: `app/races/race_watchlist.json`. Every date there has a source. Unknown values are `null`. Guesses appear only in `notes` and are marked INFERENCE.
KonfHub timestamps are in UTC. They have been converted to IST (UTC+5:30). A close of "18:30 UTC" means midnight IST, so the last full day is the day before.

Confidence: **High** means an official page or the organiser's ticketing JSON states the fact. **Medium** means an aggregator, a news report, or a mirror, or official sources disagree. **Low** means only a search summary supports it.

## Watchlist (items 1-5)

| Race | Next date | Status today | Next reg. window | Previous registration windows | Confidence |
|---|---|---|---|---|---|
| Ladakh Marathon 42.2K | Sep 2027 (not announced). Last edition: 13 Sep 2026 | not_started | not announced | 2026: **19 Feb to 23 Mar 2026** ([official](https://ladakhmarathon.com/race-information/)). 2025: not found | High (2026 window); date for 2027 unknown |
| Ladakh Marathon 21.1K | same as above | not_started | not announced | same single window for all races | High |
| The Border (Hell Race) 50K, Jaisalmer to Longewala | **19-20 Dec 2026** ([official](https://thehellrace.com/the-hell-race/the-border/)) | **closed (sold out)**. KonfHub `sold_out:true` for 50K, 100K and 100mi. The Hell Race site still shows "REGISTER NOW" | 50K ticket opened 15 Sep 2026 | 2025 (6-7 Dec): 7 Nov to **15 Nov 2025** ([KonfHub](https://konfhub.com/the-border-2025)). 2024 (14-15 Dec): 1 Jul to **21 Nov 2024 04:00 IST** ([KonfHub](https://konfhub.com/the-border-2024)) | High |
| SKF Goa River Marathon 42.2K (the "Goa River" candidate) | **13 Dec 2026** | **open**. Festival pricing ends 15 Oct 2026 | close not published | 2025: closed **25 Nov 2025** ([2025 FAQ mirror](https://www.skfgoarivermarathon.com.valmikinayak.in/faqs.php)). 2023: closed **30 Nov 2023** ([FAQ](https://goarivermarathon.com/Shop/faqs.php)) | Medium (2025 source is a mirror) |
| Goa Ultra (Hell Race) 30/60/120K (alternative "Goa" candidate) | 2027 not announced. Last edition: 8-9 Aug 2026 | not_started | not announced | 2026: 1 Mar to **19 Jul 2026** ([KonfHub](https://konfhub.com/goa-ultra-2026)) | High |
| Auroville Marathon 42.2K | **14 Feb 2027** ([official](https://www.aurovillemarathon.com/)) | not_started ("The Registration will start soon...") | not announced | 2026: closed **31 Dec 2025, 12 noon** ([FAQ](https://www.aurovillemarathon.com/faq/)). A search summary says it was extended to 10 Jan 2026 (not verified). 2025: **9 Dec 2024 to 25 Jan 2025** ([RaceMart](https://racemart.in/events/auroville-marathon-2025)) | High for the date; Medium for history |

How the ambiguous races were identified:
- **"Border Ultra / Hell Race 50 km"**: The Hell Race event "THE BORDER", on KonfHub as "THE BORDER 2026 - JAISALMER TO LAUNGEWALA | 100 MILES | 100 KM | 50 KM". The Hell Race homepage lists it as "The Border '26 registration open". No other Hell Race border event with a 50K was found ("Run the Rann" turned up nothing current). allinrunning.com/the-border sells a third-party training and travel package for this race. It is not the organiser.
- **"Goa River Ultra"**: no race by that name exists. The SKF Goa River Marathon matches the name but has no ultra; its longest race is the 42.2K. The Hell Race Goa Ultra is a real ultra, but it runs in August with 30, 60 and 120 km categories and no 50 km. Both are in the seed, so the user can delete the wrong one.

## NCR 50 km races (item 6): Nov 2026 to Jan 2027

| Race | Date | Distance from Delhi | Status | Reg. closes | Previous windows | Confidence |
|---|---|---|---|---|---|---|
| SOHNA by CapitalTrails, Ultra ~50K (self-supported) | **1 Nov 2026** | ~50 km (Sohna) | open (capped at about 30 per category, with a waitlist) | **28 Oct 2026 23:59** ([Webscorer](https://www.webscorer.com/register?raceid=427024)) | First ultra edition, so none | High |
| 2nd Columbia Trail Race 50K (Coach Ravinder) | **1 Nov 2026** | ~35 km (Mangar) | open; early-bird price until 12 Oct | **24 Oct 2026** or earlier if full ([official](https://columbiatrailrace.pfsindia.in/)) | Jan 2026 edition (8th Aravali Trail Run): closed 19 Jan 2026 ([RaceMart](https://www.racemart.in/events/8th-aravali-trail-run)). Nov 2024 (7th ATR): 4 Jun to 18 Nov 2024 ([KonfHub](https://konfhub.com/7th-aravali-trail-run)) | High |
| Mussoorie Ultra 50K (2nd ed.) | **29 Nov 2026** (Mepass lists 22 Nov) | ~290 km (just outside the range) | open (300+ registered per [Garhwal Post](https://garhwalpost.in/tom-alters-dream-mussoorie-ultra-marathon-to-be-held-on-29-nov/)) | not published | 2025 edition: dates not found | Medium |
| 6th Sundown Run 50K (night run, Gurugram) | **19 Dec 2026** | ~30 km | open; early-bird price until 19 Oct | **14 Dec 2026** or when full ([official](https://sundownrun.pfsindia.in/)) | 20 Dec 2025 and 31 May 2025 editions had a 50K; their windows were not found | High |
| Garhwal Highline 50K (Globeracers) | **25 Dec 2026** (race days 25-27 Dec) | Rishikesh-Uttarkashi area, route TBA, about 240 km or more | open (live form; inferred) | **10 Dec 2026** ([official](https://globeracers.run/races/garhwal-highline)) | Successor to the Uttarkashi 135 Mile Ultra; no history found | Medium |

Races just outside the window (also in the seed, with the reason in their notes):
- **Bhatti Lakes Ultra 50K**: 24 Oct 2026, Asola Bhatti. Registration is open and closes **10 Oct 2026** ([official](https://globeracers.run/races/bhatti-lakes)).
- **Red Stone Ultra 50K** (Hell Race, Gurugram Aravallis): the official page says **7 Feb 2027**, but the same page is still titled 2026, so the date is medium confidence. Registration has not started. Previous windows: 14 Dec 2025 to 31 Jan 2026, and 1 Nov 2024 to 15 Jan 2025 ([KonfHub](https://konfhub.com/red-stone-ultra-2026)).

Checked and excluded:
- Dehradun Ultra Run 50K: 14 Mar 2027 ([official](https://www.dehradunultrarun.com/event.html)).
- Globeracers Outpace 50K: Feb 2026 edition; 2027 not announced.
- Trail-a-thon: Mar 2026.
- IAU 50K World Championships Delhi: Mar 2026.
- Shivalik Ultra (Panchkula): no 2026 edition found.

## Scraping notes

| scrape_url | Fetch method | Patterns |
|---|---|---|
| ladakhmarathon.com/race-information/, /rules-regulations/, /sign-up/ | Plain HTTP works (WordPress, ~300 KB) | The open/close sentence is `Registrations for the (\d+)th edition of the Ladakh Marathon will open on <weekday> <d>th <Month> <yyyy> and close on ...`. The ordinals are split by HTML (`19 <sup>th</sup>`), so strip tags first. "Registration Closed" appears 6 times while closed. **Warning:** the nav has "Register Now" all year (Wayback shows it in 2025), so it is not an open signal. Watch for "14th edition" or "2027". |
| konfhub.com/<slug> (the-border-2026, goa-ultra-2027, red-stone-ultra-2027) | Plain HTTP works; the server-rendered HTML embeds JSON | Read `"ticket_name"`, `"start_timestamp"`, `"end_timestamp"` (UTC) and `"sold_out":true/false` per ticket. If now is between start and end and `sold_out` is false, it is open. If `sold_out` is true, it is closed. If the slug is missing (small page, no `ticket_name`), it has not started. Event dates are in `"start_date"`/`"end_date"`. Guessed slugs (-2027) may never be used. |
| thehellrace.com pages | Plain HTTP works | The "REGISTER NOW" button stays up even when KonfHub is sold out, so do not trust it. Dates appear as `START: 06:00 AM, 07 Feb, 2027` or `19-20 December 2026`. The register link's KonfHub slug shows which edition is live. |
| skfgoarivermarathon.com/registration | **JS SPA (Vite/React)**. Plain HTML is a 2.6 KB shell | Text lives in `/assets/index-*.js` and `/assets/RegistrationSection-*.js`, and the hashed names change on each deploy. Fetch the shell, find the script src, then grep the bundle for "Register Now", `targetDate:"YYYY-MM-DDTHH:MM:SS"` and "Prices increase". A headless browser is more reliable. |
| goarivermarathon.com/Shop/faqs.php | Plain HTTP works, but the content is stale (2023) | `What is the last date of registration?` followed by `Registration for all other categories will close on 30th November`. Watch for a year change. |
| aurovillemarathon.com/ , /register/, /faq/ | Plain HTTP works (WordPress/Elementor) | Not started: "The Registration will start soon...". Closed: "Registration is closed for Auroville Marathon 2026." plus "Closed" buttons. Open (expected): those phrases disappear and register links appear. Race date: `Race Day 14th Feb 2027`. FAQ: the answer after "What is the last date of registration?" (e.g. "31st Dec 2025 (12 Noon)"). |
| webscorer.com/register?raceid=427024 | Plain HTTP works | `Registration closes:` followed by `Wednesday, October 28, 2026 23:59 (GMT+5:30)`. Closed and full states use Webscorer's standard messages (not observed). |
| columbiatrailrace.pfsindia.in | Plain HTTP works | "Registration Open", "Registrations close 24th Oct 2026 or earlier if targeted slots fill". schema.org JSON-LD has `"startDate"` and `"validThrough"`. **Note:** that `validThrough` (2026-09-01) is stale and contradicts the visible text, so prefer the visible text. |
| racesregistrations.com/event/568 | **JS-rendered**; plain HTTP returns no useful text | Use the official page instead. |
| sundownrun.pfsindia.in | Plain HTTP works | "Register Now", "Registrations close 14 December or when slots fill", JSON-LD `"validThrough":"2026-12-14"`. |
| globeracers.run/races/<slug> | Plain HTTP works (Next.js server-rendered) | `Key Dates registration closes 10 Dec 2026 race RACE DAYS: 25–27 Dec 2026` (note the en dash). The homepage lists every race as `Dates : 25-27 Dec 2026`. |
| runnersduniya.com/event/mussoorie-ultra/ | Plain HTTP works | It is an aggregator and shows a "under maintenance" banner. It has the date and the Townscript link. |
| townscript.com/e/... | **JS-rendered** (5 KB shell) | A headless browser is needed. Townscript shows "Registrations closed" or "Sold out" on ticket cards. |
| racemart.in, indiarunning.com | **JS-rendered or redirecting**. Some RaceMart slugs redirect to the homepage | Not used as scrape targets. RaceMart pages that do render contain `Registration Closed` and `Opens on <date> and closes on <date>`. |
| ahotu.com, timeoutdoors.com | **Block bots (HTTP 403)** | Do not scrape. |
| ddnews.gov.in | Connection reset for the fetch tool | Do not scrape. |

General: send a browser User-Agent. Treat generic "Register Now" text as weak evidence. Prefer explicit phrases with dates, or KonfHub `sold_out` and `end_timestamp`.

### Scanner rules (optional per-race seed keys)

`app/races/scanner.py` reads these optional keys from each race in `race_watchlist.json`. If a key is missing, the default behaviour applies. The keys only control how the scanner reads pages; they do not change any researched facts.

| Key | Type | Effect |
|---|---|---|
| `ignore_phrases` | list of strings | Drops text signals whose matched phrase contains one of these strings (case-insensitive). Example: `["register now"]` for sites whose nav button stays up all year. |
| `ignore_signals` | list of statuses (`open`, `closed`, `not_started`) | Drops all *text* signals for these statuses for the race. Ticketing data still counts. |
| `trusted_urls` | list of URL prefixes | Strong text signals from these URLs outrank generic page text from other URLs. |
| `ticket_filter` | regex string | Only embedded ticket entries whose `ticket_name` matches are considered (for example, the 50 km ticket of a multi-distance event). |

Signal priority, highest first:
1. Ticketing data embedded in the page (KonfHub `sold_out`, `start_timestamp`, `end_timestamp`).
2. Strong text from a URL in `trusted_urls`.
3. Strong phrases ("registrations closed", "will open on <date>", "registrations close <date>").
4. Weak hints ("coming soon", platform links).

The scanner uses only the highest tier present. If two statuses conflict within that tier, it keeps the seed status at low confidence. The one exception is when exactly one of the conflicting statuses is backed by a dated phrase for a future date; that status wins at medium confidence. When a fetch fails, the site blocks bots, or the page is JavaScript-only, the result is `unknown`. An `unknown` result never replaces the seed status or a stored high- or medium-confidence status.

Rules applied in the seed:
- **Ladakh 42k and 21k:** `ignore_phrases: ["register now"]`, because the nav button is up all year.
- **The Border:** `ignore_phrases`, `trusted_urls: konfhub.com`, and `ticket_filter: "50\s*K|FRONTLINE"`.
- **Goa Ultra and Red Stone:** `ignore_phrases` and `trusted_urls: konfhub.com`, because the same thehellrace.com button issue applies.
