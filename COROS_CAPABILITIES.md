# COROS MCP Server Capabilities & Metric Audit

**Server Endpoint:** `https://mcp.coros.com/mcp`  
**Transport:** HTTP / SSE  
**Authentication:** OAuth 2.0 (Bearer Token via COROS Account Authorization)  
**NPM Package / Skill:** `coros-mcp`  

---

## 1. Exposed Tools & Data Schemas

| Tool Name | Scope & Description | Key Fields & Sub-fields |
|---|---|---|
| `query_workouts` | Summary of completed workouts, distance, duration, pace, elevation, split breakdowns. | `workout_id`, `name`, `sport_type`, `start_time`, `duration_s`, `distance_m`, `avg_pace_s_km`, `elevation_gain_m`, `elevation_loss_m`, `gap_s_km`, `avg_hr`, `max_hr`, `avg_cadence`, `calories`, `splits` (array of lap records) |
| `query_workout_details` | Second-by-second high resolution time series metrics per activity. | `timestamp`, `heart_rate`, `cadence`, `power_watts`, `stride_length_cm`, `ground_contact_time_ms`, `vertical_oscillation_mm`, `speed_m_s`, `altitude_m` |
| `get_fit_file` | Export raw FIT binary files for workouts (max 50 requests/day). | `workout_id`, `fit_file_url` / binary stream |
| `query_heart_rate` | Daily HR summary, continuous HR tracking, and zone distribution. | `date`, `resting_hr`, `avg_hr`, `max_hr`, `hr_zones` (Z1-Z5 distribution in seconds) |
| `query_hrv` | Daily sleeping HRV, resting heart rate trend. | `date`, `hrv_score`, `rmssd_ms`, `resting_hr`, `baseline_range` |
| `query_sleep` | Daily sleep metrics, total sleep duration, quality scores, stage breakdown. | `date`, `total_sleep_minutes`, `sleep_score`, `deep_sleep_minutes`, `light_sleep_minutes`, `rem_sleep_minutes`, `awake_minutes` |
| `query_fitness_metrics` | COROS Evolab fitness indices and threshold predictions. | `vo2max`, `threshold_pace_s_km`, `threshold_hr`, `running_fitness_score`, `race_predictions` (5k, 10k, half, marathon) |
| `query_training_load` | Training volume assessment, load balance, recovery score. | `date`, `daily_load`, `acute_load_7d`, `chronic_load_28d`, `fatigue_index`, `recovery_score_percent` |
| `query_training_schedule` | Prescribed workouts and upcoming training plan entries. | `schedule_id`, `date`, `title`, `description`, `target_distance_m`, `target_pace_range`, `status` |
| `query_daily_activity` | Daily activity tracking. | `date`, `steps`, `active_calories`, `exercise_duration_minutes` |
| `query_stress_health` | Time series stress and quick health check data. | `date`, `avg_stress`, `health_check_records` |
| `query_profile` | User profile data and connected watch/device details. | `user_id`, `gender`, `birth_date`, `weight_kg`, `height_cm`, `devices` (model, firmware) |

---

## 2. FR-1.2 Metric Availability Matrix & Fallback Plan

| Category | Requirement Metric | Status | Primary Source | Fallback Mechanism |
|---|---|---|---|---|
| **Runs** | Distance | AVAILABLE | `query_workouts.distance_m` | N/A |
| **Runs** | Duration | AVAILABLE | `query_workouts.duration_s` | N/A |
| **Runs** | Pace | AVAILABLE | `query_workouts.avg_pace_s_km` | Calculated: `duration / distance` |
| **Runs** | Splits | AVAILABLE | `query_workouts.splits` | Derived from 1-sec details if lap splits missing |
| **Runs** | Elevation gain/loss | AVAILABLE | `query_workouts.elevation_gain_m` | N/A |
| **Runs** | Grade-adjusted pace (GAP) | AVAILABLE | `query_workouts.gap_s_km` | Calculated via Minetti equation using elevation delta |
| **Runs** | Cadence | AVAILABLE | `query_workouts.avg_cadence` | N/A |
| **Runs** | Stride length | AVAILABLE | `query_workout_details.stride_length_cm` | Derived: `speed / (cadence * 2)` |
| **Runs** | Ground contact time (GCT) | AVAILABLE | `query_workout_details.ground_contact_time_ms` | Manual entry / POD 2 sensor sync |
| **Runs** | Vertical oscillation | AVAILABLE | `query_workout_details.vertical_oscillation_mm` | Manual entry / POD 2 sensor sync |
| **Runs** | Running power | AVAILABLE | `query_workouts.avg_power` | Calculated GAP power estimate |
| **Physiology** | Heart rate & HR zones | AVAILABLE | `query_heart_rate.hr_zones` | Calculated from max HR & reserve formulas |
| **Physiology** | HRV | AVAILABLE | `query_hrv.hrv_score` | N/A |
| **Physiology** | Resting HR | AVAILABLE | `query_hrv.resting_hr` | N/A |
| **Physiology** | VO2max estimate | AVAILABLE | `query_fitness_metrics.vo2max` | Daniels VDOT formula calculated from race times |
| **Sleep** | Total sleep duration | AVAILABLE | `query_sleep.total_sleep_minutes` | N/A |
| **Sleep** | Stage breakdown | AVAILABLE | `query_sleep.stages` | Manual user sleep log entry |
| **Sleep** | Sleep score | AVAILABLE | `query_sleep.sleep_score` | Derived from total duration & awakenings |
| **Load & Recovery** | Training load / TSS | AVAILABLE | `query_training_load.daily_load` | Calculated TRIMPS from HR & duration |
| **Load & Recovery** | Acute vs. Chronic load | AVAILABLE | `query_training_load.acute_load_7d` | Calculated 7d vs 28d EWMA of training load |
| **Load & Recovery** | Fatigue & Recovery index | AVAILABLE | `query_training_load.recovery_score_percent` | Calculated: `(Chronic Load - Acute Load) / Chronic Load` |
| **Body** | Weight | PARTIAL | `query_profile.weight_kg` | Manual user profile setting in app UI |
| **Body** | Other body metrics | PARTIAL | `query_profile` | Manual user profile setting in app UI |
