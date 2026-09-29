# Project History & Complete Replication Guide: Personal Running Coach

**Project Name:** Personal Running Coach — Local Flask Web Application  
**Target Environment:** Windows 10/11, Python 3.12+, Node.js LTS, SQLite  
**Integrations:** COROS MCP Gateway (`coros-mcp`), Google Gemini SDK (`google-genai`), Gemini CLI (`gemini`)  
**Last Updated:** 2026-09-29  

---

## 1. Project Overview & Core Architectural Principles

The **Personal Running Coach** is a local-first Python Flask web application designed for endurance runners. It synchronizes activity logs, sleep metrics, and daily physiological data from the official **COROS MCP Server** (`https://mcp.coros.com/mcp`), applies deterministic exercise science guardrails in Python code, and uses the **Google Gemini SDK/CLI** to generate factual, personalized coaching guidance.

### Key Architectural Rules (ADRs):
1. **Local Single-User Architecture (ADR-001)**: Uses local SQLite (`coach.db`) with zero external cloud DB dependencies.
2. **Deterministic Safety Guardrails (ADR-002)**: Exercise science rules (10% volume increase cap, no back-to-back hard days, max 4 consecutive active days, 80-20 intensity distribution) are strictly enforced in Python code (`app/engine/guardrails.py`), NOT left to LLM prompt adherence.
3. **Non-Interactive LLM Invocation (ADR-003)**: Interacts with Gemini CLI via stdin (`gemini -p -`) with explicit 30s timeouts, retries, and fallback handling. Also supports the `google-genai` Python SDK directly (prioritized when API key is available).
4. **Factual Context Builder (ADR-004)**: Assembles factual runner context without fabricated or hallucinated metrics. Missing fields are explicitly preserved as `NULL` or displayed as `"Not Available"` (NFR-4.1).
5. **Dark Athletic Design System (ADR-005)**: High-contrast dark theme (`#0a0c0e`), runner orange accent (`#ff5500`), Google Fonts (`Teko` display, `Inter` body), and glassmorphism card elevation.

---

## 2. Complete File Structure Map

```text
Coros_MCP/
├── .env.example                     # Environment template (FLASK_ENV, DATABASE_PATH, COROS_MCP_SERVER_URL)
├── .gitignore                       # Git ignore file (.venv, coach.db, *.pyc, .pytest_cache)
├── COROS_CAPABILITIES.md            # COROS MCP Server tool audit & capabilities documentation
├── DECISIONS.md                     # Architectural Decision Records (ADR-001 to ADR-005)
├── history.md                       # Complete project replication and sprint history guide
├── requirements.txt                 # Pinned Python package dependencies
├── coach.db                         # Local SQLite database (created on init)
├── mcp_response.json               # Sample COROS MCP API response for development reference
├── demo_3_profiles.py              # Demo script testing 3 runner profiles end-to-end
├── app/
│   ├── __init__.py                  # Application package initialization
│   ├── cli.py                       # Flask CLI commands (`flask sync run`)
│   ├── data/
│   │   ├── __init__.py
│   │   ├── db.py                    # Connection factory, schema migration logic, column auto-migration
│   │   ├── models.py                # Data classes for activities, sleep, and physiology
│   │   ├── queries.py               # SQLite queries for dashboard, plans, S&C, compliance, and profile
│   │   ├── schema.sql               # Full DDL schema for all tables
│   │   └── sync.py                  # Full & incremental sync engine with transaction safety
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── guardrails.py            # Deterministic exercise science safety rules
│   │   ├── planner.py               # Literature methodology router (Road VDOT/Pfitzinger vs Ultra)
│   │   ├── strength.py              # Runner S&C engine with niggle safety filtering & periodisation
│   │   └── tracking.py              # Post-run feedback, overtraining risk engine (ACWR/HRV/sleep), workout adherence calculator
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── context_builder.py       # Factual runner context assembly (~350 tokens)
│   │   └── gemini_cli.py            # Gemini SDK/CLI wrapper with retries, timeouts, intelligent fallback
│   ├── mcp_client/
│   │   ├── __init__.py
│   │   └── coros_client.py          # Interface to official coros-mcp CLI gateway, OAuth login, token validation
│   ├── prompts/
│   │   ├── coach_chat_v1.txt        # Prompt template for Coach Chat AI assistant
│   │   └── plan_generation_v1.txt   # Prompt template for structured plan rationale
│   ├── static/
│   │   ├── css/
│   │   │   └── style.css            # Dark athletic CSS design system
│   │   └── js/
│   │       └── charts.js            # Chart.js trend visualizations (Volume, Sleep, Physio)
│   ├── templates/
│   │   ├── base.html                # Main navigation layout, header, COROS connection status badge
│   │   ├── dashboard.html           # KPI grid (with time windows), trend charts, activity history with window filtering, 1-click sync, COROS auth banner
│   │   ├── activity_detail.html     # Workout metrics, lap splits, N/A fallback badges
│   │   ├── plan.html                # Active plan cards, compliance stats, session logging, discard plan, HR/Pace focus styling, adherence rating badges
│   │   ├── block_summary.html       # 4-week microcycle summary reports & fatigue alerts
│   │   ├── strength.html            # Prescribed S&C workouts, exercise cues, niggle safety alerts
│   │   ├── profile.html             # Goal race profile, available days, niggle inputs
│   │   ├── chat.html                # Coach Chat natural language assistant interface, Gemini API key configuration
│   │   └── error.html               # User-friendly error page with suppressed stack traces
│   └── web/
│       ├── __init__.py
│       └── routes.py                # Flask web route handlers, COROS auth route, error boundaries
└── tests/
    ├── test_gemini.py               # Gemini CLI availability smoke test
    ├── test_benchmark_sync.py       # Sync speed benchmark (< 60s target)
    ├── test_db_schema.py            # Schema creation & migration tests
    ├── test_plan_engine.py          # Guardrails & 3-profile plan generation tests
    ├── test_profile_and_llm.py      # Profile saving & LLM wrapper integration tests
    ├── test_skeleton.py             # Flask application factory tests
    ├── test_strength_engine.py      # S&C engine, niggle filtering & periodisation tests
    ├── test_sync_engine.py          # Data sync idempotency & NULL preservation tests
    ├── test_tracking_and_adaptation.py # Post-run feedback, overtraining triggers & plan adaptation tests
    ├── test_user_improvements.py    # User feedback improvements & bug fix validation tests (8 tests)
    └── test_web_routes.py           # Web route HTTP response & error handler tests
```

---

## 3. Chronological Sprint Delivery Summary

### Sprint 0 — Discovery, Environment & Architecture Setup
- **Environment**: Python 3.12.10, `.venv` virtual environment, Node.js v24 LTS.
- **Dependencies**: 56 pinned packages saved to `requirements.txt` (`flask==3.1.3`, `google-genai==2.24.0`, `mcp==2.2.0`, `pytest==9.1.1`, etc.).
- **COROS MCP Audit**: Documented tool capabilities in `COROS_CAPABILITIES.md`.
- **Architectural Decisions**: Established ADR-001 through ADR-005 in `DECISIONS.md`.

### Sprint 1 — Data Layer & Sync Engine
- **Database Schema**: Created `schema.sql` defining `activities`, `activity_splits`, `sleep_records`, `daily_physiology`, and `sync_logs`.
- **Sync Engine**: Built `app/data/sync.py` supporting full (1-year) and incremental syncs, transaction safety (`BEGIN/COMMIT/ROLLBACK`), idempotency (0 duplicates on re-run), and missing field NULL preservation.
- **CLI Command**: Implemented `flask sync run --full` / `--incremental`. Benchmarked 1-year sync at **0.023 seconds** (well under 60s NFR-5.2 limit).

### Sprint 2 — Web Shell & Dashboard View
- **Design System**: Implemented `app/static/css/style.css` (dark `#0a0c0e` theme, Google Fonts `Teko` & `Inter`, runner orange `#ff5500` accent, 390px mobile grid).
- **Dashboard (`/`)**: Built KPI cards (Volume, Elevation, Sleep, ACWR), Chart.js trend charts (`app/static/js/charts.js`), and recent activities list.
- **Activity Detail (`/activity/<id>`)**: Built workout detail view with lap splits table and explicit `"Not Available"` / `"N/A"` fallback badges for missing metrics (NFR-4.1).
- **Hardening**: Built `app/templates/error.html` with suppressed stack traces. Load time benchmarked at **12.45 ms** (< 1.0s target NFR-5.1).

### Sprint 3 — Goal Profile, Prompt System & LLM Integration
- **Profile DB & UI**: Added `user_profile` table and `/profile` view capturing race distance, target time, available days, weekly hours, injury history, and current niggles.
- **Context Builder**: Created `app/llm/context_builder.py` assembling factual runner context.
- **Gemini CLI Wrapper**: Built `app/llm/gemini_cli.py` invoking `gemini -p -` via stdin with 30s timeout, retries, and fallback text.
- **Coach Chat (`/chat`)**: Built interactive natural language coaching interface with AJAX rendering and loading state.

### Sprint 4 — Plan Generation Engine & Guardrails
- **Plan DB Schema**: Added `training_plans` and `plan_sessions` tables.
- **Deterministic Guardrails**: Created `app/engine/guardrails.py` enforcing <=10% volume increase cap, no back-to-back hard days, max 4 consecutive training days, and >=80% easy volume (80-20 rule).
- **Plan Engine**: Built `app/engine/planner.py` implementing literature methodology routing (Daniels' VDOT & Pfitzinger for Road vs Uphill Athlete for Ultra).
- **Plan UI (`/plan`)**: Built weekly plan view rendering target volume, session purpose, target pace/HR zones, and methodology rationale. Verified end-to-end plan generation for 10K, Marathon, and 50K Ultra profiles.

### Sprint 5 — Tracking, Feedback & Adaptation
- **Tracking Schema**: Added tracking columns (`matched_activity_id`, `status`, `actual_distance_km`, `actual_duration_min`, `actual_avg_pace_s_km`, `actual_avg_hr`, `post_run_feedback`) to `plan_sessions` and created `block_summaries` table.
- **Feedback & Overtraining Engine**: Built `app/engine/tracking.py`:
  - `generate_post_run_feedback()`: Compares actual vs prescribed distance, pace, and HR to produce factual coaching guidance.
  - `detect_overtraining_risk()`: Evaluates ACWR (>1.35), HRV degradation (>10% drop), and sleep score (<65 for 3 days) over rolling 7 days.
- **Adaptive Planner**: Updated `TrainingPlanner.generate_plan()` to cap volume build at 0% when compliance < 70% and enforce -20% to -30% deload reduction when fatigue flags trigger.
- **Block Summary UI (`/block-summary`)**: Built 4-week microcycle performance summary view.

### Sprint 6 — Strength & Conditioning Integration
- **S&C DB Schema**: Added `strength_exercises` library auto-seeded with 11 runner exercises (Single-Leg, Hinge, Squat, Core, Ankle/Calf, Upper Body, Plyo) and `strength_workouts` table.
- **S&C Engine**: Built `app/engine/strength.py` implementing niggle contraindication safety filtering (knee, calf, Achilles, lower back, hamstring) and running phase periodisation (Base: 3x10-12 RPE 7, Build: 3x5-6 RPE 8, Peak: 3x4 RPE 8, Taper: 2x6 RPE 5).
- **S&C UI (`/strength`)**: Built S&C workout view with exercise cards, safety substitution alert banners, phase buttons, and completion tracking.

### Sprint 7 — Polishing, Bug Fixes & Application Hardening
- **Dashboard Sync Button (Bug 1 Fix)**: Added `🔄 Sync Pending Data` and `📅 Sync 365 Days History` buttons (`POST /sync`) with status alerts on `/`.
- **Discard Training Plan Button (Bug 2 Fix)**: Added `🗑️ Discard Plan` button (`POST /plan/discard`) allowing instant plan resetting.
- **COROS MCP Gateway CLI Integration**: Integrated `CorosMCPClient` with official `coros-mcp` CLI (`querySportRecords`, `queryTrainingLoadAssessment`, `queryFitnessAssessmentOverview`, `queryRecoveryStatus`, `querySleepData`, `querySleepHrv`).
- **Auto-Login Trigger**: Configured 1-click browser OAuth login launching `npx coros-mcp login` automatically when unauthenticated.
- **Sprint 7 Test Suite**: All 33 unit and integration tests passing in 8.35s.

### Sprint 7+ — User Feedback Improvements (Round 1: 5 Items)

All 5 user-requested improvements were completed and verified:

#### Improvement 1: Dashboard Last Sync Date Display
- **Files Changed**: `app/data/queries.py`, `app/templates/dashboard.html`
- **What**: `get_dashboard_summary()` now queries the `sync_logs` table for the most recent `timestamp` and formats it as `last_sync_display` (e.g. `"2026-09-28 14:30"`).
- **UI**: Dashboard header shows `📅 Last Synced with COROS: <timestamp>` or `"Never — sync your data to begin!"` if no syncs have occurred.

#### Improvement 2: Explicit Time Windows on KPI Cards & Charts
- **Files Changed**: `app/templates/dashboard.html`
- **What**: Updated all KPI card headers and chart titles to explicitly state their data window:
  - `"Weekly Volume (Last 7 Days)"`, `"Weekly Elevation (Last 7 Days)"`
  - `"Sleep Score (Latest Night)"`, `"Acute:Chronic Load (7d/28d Ratio)"`
  - Chart: `"Weekly Volume & Distance (Last 12 Weeks)"`, `"Sleep Duration & Quality (Last 30 Days)"`

#### Improvement 3: Recent Activities Window Filtering
- **Files Changed**: `app/web/routes.py`, `app/data/queries.py`, `app/templates/dashboard.html`
- **What**:
  - `routes.py` `index()`: Added `days = request.args.get("days", default=30, type=int)` and passes `selected_days` to template.
  - `queries.py` `get_recent_activities()`: Accepts `days` parameter, with `days=0` returning all activities.
  - `dashboard.html`: Added filter buttons: **7 Days**, **30 Days (1 Mo)**, **90 Days**, **All Time** — with active state highlighting.

#### Improvement 4: Training Plan Target Focus (HR vs Pace) with Numeric Ranges
- **Files Changed**: `app/engine/planner.py`, `app/templates/plan.html`
- **What**:
  - `planner.py` `_build_road_plan()` and `_build_ultra_plan()`: Updated all `target_pace_or_hr` fields to explicitly state focus type with ranges. Examples:
    - `"Heart Rate Focus: 130 – 145 bpm (Zone 2 Easy, 6:00 – 6:30 /km)"`
    - `"Pace Focus: 5:15 – 5:30 /km (Zone 4 LT, 158 – 170 bpm)"`
  - `plan.html`: Added conditional rendering with ❤️ for HR Focus (red badge) and ⏱️ for Pace Focus (orange badge).

#### Improvement 5: Coach Chat Intelligent Fallback
- **Files Changed**: `app/llm/gemini_cli.py`, `tests/test_profile_and_llm.py`
- **What**: Added `_generate_intelligent_fallback()` method to `GeminiCLIWrapper` that produces context-aware coaching responses when both Gemini SDK and CLI fail. Covers topics: easy run pacing, heart rate zones, training structure, recovery, race preparation.

### Sprint 7++ — Bug Fixes (Round 2: 5 Items)

All 5 user-reported bugs were fixed and verified:

#### Bug Fix 1: Sync Status Messaging on Dashboard
- **Files Changed**: `app/web/routes.py`, `app/templates/dashboard.html`
- **What**: The `perform_sync()` function returns a `(success, count, msg, duration)` tuple. After sync completes, the user is redirected with `sync_msg` and `sync_status` URL parameters, and the dashboard displays a colored banner:
  - ✅ Green banner for successful sync with record count
  - ❌ Red banner for failed sync with error message

#### Bug Fix 2: COROS Authentication on First Page Load
- **Files Changed**: `app/web/routes.py`, `app/templates/base.html`, `app/templates/dashboard.html`
- **What**:
  - `routes.py`: Added `CorosMCPClient` import and `/coros/login` route (`coros_login()`) that triggers `npx coros-mcp login`.
  - `base.html`: Added COROS connection status badge in navbar — 🟢 `"Connected"` when authenticated, 🔴 `"Connect COROS Account"` button when not.
  - `dashboard.html`: Prominent auth banner when unauthenticated: `"🔑 Authenticate COROS via Browser"` button.

#### Bug Fix 3: COROS Token Validation
- **Files Changed**: `app/mcp_client/coros_client.py`, `app/web/routes.py`
- **What**:
  - `coros_client.py`: Added `validate_token_status()` method returning `{is_authenticated, token_exists, status_code, message}`.
    - Token path: `~\.coros-mcp-skill-gateway-ts\us\token.json`
    - Checks: file exists → parse JSON → check `access_token` field → check `expires_at` if present.
  - `routes.py`: Both `index()` and `plan_view()` call `validate_token_status()` and pass `coros_auth` dict to templates.

#### Bug Fix 4: Coach Chat Gemini Integration
- **Files Changed**: `app/llm/gemini_cli.py`, `app/data/db.py`, `app/data/queries.py`, `app/templates/chat.html`
- **What**:
  - `gemini_cli.py` `ask_coach()`: Reordered priority: (1) GenAI SDK with API key (checks `GEMINI_API_KEY`, `GOOGLE_API_KEY`, or `user_profile.gemini_api_key`), (2) CLI subprocess, (3) intelligent fallback.
  - `db.py` `init_db()`: Added migration for `user_profile.gemini_api_key TEXT` column.
  - `queries.py`: Updated `get_user_profile()` and `save_user_profile()` to include `gemini_api_key`.
  - `chat.html`: Added collapsible `"🔑 Configure Gemini API Key"` section with save button and `saveApiKey()` JavaScript function.

#### Bug Fix 5: Training Plan Auto-Match & Workout Adherence Rating
- **Files Changed**: `app/engine/tracking.py`, `app/data/queries.py`, `app/data/db.py`, `app/templates/plan.html`, `app/web/routes.py`
- **What**:
  - `tracking.py`: Added `calculate_workout_adherence(session, actual)` function:
    - Distance adherence: 60% weight (100% if within ±15%, scales down to 0%)
    - Intensity adherence: 40% weight (HR-based if HR target, pace-based if pace target)
    - Returns `(score, rating_label)` with emoji badges: 🌟 Excellent (≥90%), ✅ Good (≥75%), ⚠️ Fair (≥50%), ❌ Poor (<50%)
  - `queries.py` `update_session_status()`: Calculates and stores `adherence_score` and `adherence_rating`.
  - `queries.py` `auto_match_activities_to_sessions()`: Calculates adherence for auto-matched workouts.
  - `db.py`: Added migration for `plan_sessions.adherence_score REAL` and `plan_sessions.adherence_rating TEXT`.
  - `plan.html`: Displays `"🎯 Workout Adherence Rating: ..."` badge on completed sessions.
  - `routes.py` `plan_view()`: Auto-calls `auto_match_activities_to_sessions()` on page load.

---

## 4. Database Schema Summary

### Core Tables (Sprint 1)
| Table | Purpose |
|-------|---------|
| `activities` | Synced COROS activities (id, date, sport_type, name, distance_m, duration_s, avg_pace_s_km, avg_hr, elevation_gain_m, etc.) |
| `activity_splits` | Per-km or per-lap split data linked to activities |
| `sleep_records` | Nightly sleep data (total_sleep_minutes, sleep_score) |
| `daily_physiology` | Daily body metrics (resting_hr, hrv_score, acute_load, chronic_load) |
| `sync_logs` | Sync audit trail (timestamp, sync_type, status, records_fetched, error_message, duration_ms) |

### Profile & Planning Tables (Sprint 3-4)
| Table | Purpose |
|-------|---------|
| `user_profile` | Runner goal profile (race_distance, target_time, available_days, weekly_hours, injury_history, current_niggles, **gemini_api_key**) |
| `training_plans` | Generated plan metadata (methodology, total_weeks, start_date, status) |
| `plan_sessions` | Individual workout sessions with tracking columns (**adherence_score**, **adherence_rating**) |

### Tracking & S&C Tables (Sprint 5-6)
| Table | Purpose |
|-------|---------|
| `block_summaries` | 4-week microcycle performance summaries |
| `strength_exercises` | Exercise library (11 runner exercises, auto-seeded) |
| `strength_workouts` | Completed S&C workout records |

### Column Migrations (auto-applied in `init_db()`)
The following columns are automatically added if missing via `ALTER TABLE` migrations in `app/data/db.py`:
- **`plan_sessions`**: `matched_activity_id`, `status`, `user_notes`, `actual_distance_km`, `actual_duration_min`, `actual_avg_pace_s_km`, `actual_avg_hr`, `post_run_feedback`, `adherence_score`, `adherence_rating`
- **`user_profile`**: `gemini_api_key`

---

## 5. Key Technical Details & Known Issues

### Gemini Integration Priority Chain
The coach chat system (`app/llm/gemini_cli.py`) tries three methods in order:
1. **Google GenAI SDK** (`google-genai` package) — requires `GEMINI_API_KEY` or `GOOGLE_API_KEY` environment variable, or the key saved in `user_profile.gemini_api_key` column. This is the **recommended** path.
2. **Gemini CLI** (`gemini -p -` subprocess) — currently fails with exit code 41 if `~/.gemini/settings.json` has `"selectedType": "gca"`. Only works with valid CLI auth.
3. **Intelligent Fallback** — `_generate_intelligent_fallback()` provides context-aware coaching responses covering easy run pacing, heart rate zones, training structure, recovery, and race prep. Does not require any API key.

### COROS Authentication
- **Token Path**: `C:\Users\<user>\.coros-mcp-skill-gateway-ts\us\token.json`
- **Login Trigger**: `npx -y coros-mcp login` launches a browser OAuth flow.
- **Validation**: `validate_token_status()` checks file existence → JSON parse → `access_token` presence → optional `expires_at` check.
- **Web UI**: Navbar shows 🟢 Connected / 🔴 Connect button. Dashboard shows prominent auth banner if unauthenticated.

### Known Deprecation Warnings
- `datetime.utcnow()` is deprecated in Python 3.12+. Appears in `coros_client.py` and `test_web_routes.py`. Should be migrated to `datetime.now(datetime.UTC)` in a future sprint.

---

## 6. Complete Setup & Replication Instructions

Follow these exact steps to set up and run the application from scratch on any machine.

### Step 1: Environment & Virtual Environment
Open PowerShell in your project directory:
```powershell
# Create Python 3.12 virtual environment
python -m venv .venv

# Activate virtual environment
.\.venv\Scripts\Activate.ps1
```

### Step 2: Install Python Dependencies
```powershell
pip install -r requirements.txt
```

### Step 3: Install COROS MCP CLI
```powershell
npm install -g coros-mcp
```

### Step 4: Configure Environment Variables
Create a `.env` file in the project root:
```env
FLASK_ENV=development
FLASK_APP=app.web.routes:create_app
DATABASE_PATH=coach.db
COROS_MCP_SERVER_URL=https://mcp.coros.com/mcp
```

**Optional (for live Gemini coaching):** Add your Gemini API key:
```env
GEMINI_API_KEY=your-api-key-here
```
Or configure it through the Coach Chat page UI after launch.

### Step 5: Initialize Local SQLite Database
Run Python script to initialize database tables, apply all column migrations, and seed exercise libraries:
```powershell
python -c "from app.data.db import init_db; init_db()"
```

### Step 6: Authenticate with COROS MCP Server
**Option A — Via Web UI (recommended):** Just start the app and click the "Connect COROS Account" button in the navigation bar. This launches browser OAuth automatically.

**Option B — Via CLI:**
```powershell
cmd /c "set PATH=C:\Program Files\nodejs;%PATH% & npx -y coros-mcp login"
```

### Step 7: Start the Web Application
```powershell
python -m flask --app app.web.routes:create_app run --port 5000
```
Open `http://127.0.0.1:5000` in your web browser.

### Step 8: Run Full Unit & Integration Test Suite
To verify that all 41 test cases pass:
```powershell
.\.venv\Scripts\pytest -v
```

---

## 7. Verification & Test Suite Results

```text
============================== 41 passed in 50.82s ==============================
test_gemini.py::test_gemini_cli PASSED                                   [  2%]
tests/test_benchmark_sync.py::test_12_month_sync_under_60_seconds PASSED [  4%]
tests/test_db_schema.py::test_tables_created PASSED                      [  7%]
tests/test_db_schema.py::test_activity_insert_and_query PASSED           [  9%]
tests/test_plan_engine.py::test_guardrail_volume_increase PASSED         [ 12%]
tests/test_plan_engine.py::test_guardrail_no_back_to_back_hard_days PASSED [ 14%]
tests/test_plan_engine.py::test_guardrail_max_consecutive_days PASSED    [ 17%]
tests/test_plan_engine.py::test_guardrail_80_20_intensity PASSED         [ 19%]
tests/test_plan_engine.py::test_end_to_end_plan_generation_for_3_profiles PASSED [ 21%]
tests/test_profile_and_llm.py::test_profile_get_and_post PASSED          [ 24%]
tests/test_profile_and_llm.py::test_factual_context_builder PASSED       [ 26%]
tests/test_profile_and_llm.py::test_versioned_prompt_template_loader PASSED [ 29%]
tests/test_profile_and_llm.py::test_gemini_cli_wrapper_and_error_handling PASSED [ 31%]
tests/test_profile_and_llm.py::test_chat_route_endpoint PASSED           [ 34%]
tests/test_skeleton.py::test_flask_app_creation PASSED                   [ 36%]
tests/test_skeleton.py::test_volume_guardrail_rule PASSED                [ 39%]
tests/test_strength_engine.py::test_seed_and_get_available_exercises PASSED [ 41%]
tests/test_strength_engine.py::test_niggle_safety_contraindication_filtering PASSED [ 43%]
tests/test_strength_engine.py::test_strength_engine_phase_periodisation PASSED [ 46%]
tests/test_strength_engine.py::test_strength_web_routes PASSED           [ 48%]
tests/test_sync_engine.py::test_full_sync_ingestion_and_null_preservation PASSED [ 51%]
tests/test_sync_engine.py::test_idempotency_zero_duplicates_on_rerun PASSED [ 53%]
tests/test_sync_engine.py::test_sync_failure_logging_and_transaction_safety PASSED [ 56%]
tests/test_tracking_and_adaptation.py::test_post_run_feedback_generation PASSED [ 58%]
tests/test_tracking_and_adaptation.py::test_auto_match_activities_to_sessions PASSED [ 60%]
tests/test_tracking_and_adaptation.py::test_weekly_compliance_calculation PASSED [ 63%]
tests/test_tracking_and_adaptation.py::test_overtraining_risk_detection PASSED [ 65%]
tests/test_tracking_and_adaptation.py::test_adaptive_plan_regeneration PASSED [ 68%]
tests/test_user_improvements.py::test_dashboard_last_sync_display PASSED [ 70%]
tests/test_user_improvements.py::test_dashboard_kpi_time_windows PASSED  [ 73%]
tests/test_user_improvements.py::test_recent_activities_window_filtering PASSED [ 75%]
tests/test_user_improvements.py::test_training_plan_target_focus_and_ranges PASSED [ 78%]
tests/test_user_improvements.py::test_coach_chat_returns_personalized_guidance PASSED [ 80%]
tests/test_user_improvements.py::test_coros_auth_status_validation PASSED [ 82%]
tests/test_user_improvements.py::test_workout_adherence_calculator PASSED [ 85%]
tests/test_user_improvements.py::test_training_plan_auto_match_and_adherence_rating PASSED [ 87%]
tests/test_web_routes.py::test_dashboard_route_renders_data PASSED       [ 90%]
tests/test_web_routes.py::test_activity_detail_renders_form_metrics_and_na_badges PASSED [ 92%]
tests/test_web_routes.py::test_404_error_suppresses_stack_trace PASSED   [ 95%]
tests/test_web_routes.py::test_sync_route_endpoint PASSED                [ 97%]
tests/test_web_routes.py::test_plan_discard_route_endpoint PASSED        [100%]
```

### Test Coverage by Module

| Test File | Tests | Covers |
|-----------|-------|--------|
| `test_gemini.py` | 1 | Gemini CLI availability smoke test |
| `test_benchmark_sync.py` | 1 | Sync performance (< 60s NFR) |
| `test_db_schema.py` | 2 | Schema creation, activity insert/query |
| `test_plan_engine.py` | 5 | All 4 guardrails + end-to-end plan generation for 3 profiles |
| `test_profile_and_llm.py` | 5 | Profile CRUD, context builder, prompt loader, LLM wrapper, chat route |
| `test_skeleton.py` | 2 | App factory, volume guardrail rule |
| `test_strength_engine.py` | 4 | Exercise seeding, niggle filtering, phase periodisation, S&C routes |
| `test_sync_engine.py` | 3 | Full sync, idempotency, failure logging |
| `test_tracking_and_adaptation.py` | 5 | Post-run feedback, auto-match, compliance, overtraining, adaptive regen |
| `test_user_improvements.py` | 8 | All Round 1 improvements + Round 2 bug fixes |
| `test_web_routes.py` | 5 | Dashboard, activity detail, 404, sync endpoint, plan discard |
| **Total** | **41** | |

---

## 8. Files Changed Per Sprint (Round 1 & 2 Details)

### Round 1: User Improvements — Files Changed

| File | What Changed |
|------|-------------|
| `app/data/queries.py` | Added `last_sync_display` to `get_dashboard_summary()`; `get_recent_activities()` accepts `days` param; `get_user_profile()` / `save_user_profile()` include `gemini_api_key` |
| `app/templates/dashboard.html` | Added last sync display, KPI time windows in card headers, activity filter buttons (7/30/90/All), COROS auth banner |
| `app/engine/planner.py` | Updated `target_pace_or_hr` in `_build_road_plan()` and `_build_ultra_plan()` with explicit HR/Pace focus labels and numeric bpm/pace ranges |
| `app/templates/plan.html` | Added conditional ❤️/⏱️ target focus styling with colored badges |
| `app/llm/gemini_cli.py` | Added `_generate_intelligent_fallback()`, reordered `ask_coach()` to prioritize GenAI SDK |
| `app/web/routes.py` | Added `days` query param, `CorosMCPClient` import, `coros_login()` route, `coros_auth` in templates, auto-match on plan load |
| `tests/test_profile_and_llm.py` | Updated assertion to accept new fallback format |

### Round 2: Bug Fixes — Files Changed

| File | What Changed |
|------|-------------|
| `app/mcp_client/coros_client.py` | Added `validate_token_status()` method |
| `app/web/routes.py` | Added `/coros/login` route, `validate_token_status()` calls in index/plan_view, re-raise in testing mode |
| `app/templates/base.html` | Added COROS connection status badge (🟢/🔴) in navbar |
| `app/templates/dashboard.html` | Added prominent auth banner when unauthenticated |
| `app/templates/chat.html` | Added collapsible Gemini API key configuration section with `saveApiKey()` JS |
| `app/llm/gemini_cli.py` | Added `db_path` param to `ask_coach()`, Gemini SDK API key lookup from profile |
| `app/data/db.py` | Added column migrations for `adherence_score`, `adherence_rating`, `gemini_api_key` |
| `app/data/queries.py` | Updated `update_session_status()` and `auto_match_activities_to_sessions()` with adherence calculation |
| `app/engine/tracking.py` | Added `Tuple` import, added `calculate_workout_adherence()` function |
| `app/templates/plan.html` | Added adherence rating badge display on completed sessions |
| `tests/test_user_improvements.py` | Created with 8 comprehensive tests |

---

## 9. Web Application Page Guide

| URL | Page | Key Features |
|-----|------|--------------|
| `/` | Dashboard | KPI cards with time windows, trend charts (12-week volume, 30-day sleep), recent activities with day filter (7/30/90/All), sync buttons, COROS auth status, last sync date |
| `/activity/<id>` | Activity Detail | Workout metrics, lap splits table, N/A fallback badges |
| `/plan` | Training Plan | Weekly plan cards with HR/Pace focus badges, compliance stats, session logging, discard button, auto-match with adherence ratings |
| `/block-summary` | Block Summary | 4-week microcycle performance reports, fatigue alerts |
| `/strength` | Strength & Conditioning | Phase-periodised S&C workouts, niggle safety filtering, exercise cards |
| `/profile` | Runner Profile | Goal race, available days, weekly hours, injury history, niggles |
| `/chat` | Coach Chat | Natural language coaching via Gemini SDK, API key config, intelligent fallback |
| `/sync` (POST) | Sync Trigger | Full/incremental COROS data sync with status reporting |
| `/plan/discard` (POST) | Discard Plan | Instant plan reset |
| `/coros/login` | COROS Login | Browser OAuth trigger via coros-mcp CLI |
