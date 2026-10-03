# COROS MCP Capability Matrix

Verified 2026-09-29 against the official COROS MCP gateway (`npx -y coros-mcp call-tool`, US region, PACE 3 account) using `scripts/coros_smoke_test.py`. Raw outputs: `scripts/smoke_output/<tool>.txt`; machine summary: `scripts/smoke_output/summary.json`.

The previous version of this file listed invented tool names (`query_workouts`, `query_sleep`, ...) and fields. Those do not exist. The real catalog has 34 tools (below).

## Output format rules (important for parsing)

- The CLI prints a wrapper `{"content":[{"type":"text","text":...}],"isError":bool}`. Errors can also arrive on stderr with exit code 1 (`error: mcp tools/call failed: {...}`).
- Most tools return **human-readable text that is JSON-string-encoded** (the `text` value starts with `"`, so it needs a second `json.loads`), and then must be regex-parsed. Only `queryActivityLapData` and `queryCustomActivityLapData` return real JSON objects; `queryActivityFitFileDownloadUrls` returns plain text.
- Dates are `yyyyMMdd`. Sleep dates are wake-up days. Each call takes about 4-5 s (npx start-up).
- Activity-level tools need `labelId` + `sportType` from `querySportRecords` (line `LabelId: 480... | SportType: 100`; running = 100). `querySportRecords` also prints `startTimestamp`/`endTimestamp`.

## Read tools (readOnlyHint = true), verified 2026-09-29

| Tool | Purpose / required args | Works | Key fields in real output | Coach-app use |
|---|---|---|---|---|
| `querySportRecords` | List workouts. Optional startDate, endDate, sportTypeCodes[], min/maxDistanceKm, min/maxDurationMinutes, maxAveragePace, locationKeyword, limit (200 accepted) | yes | Per record: sport name, date, "Location" (actually the workout title), start coordinates, startTimestamp/endTimestamp, Duration, Distance, Average Pace, Avg HR, Calories, LabelId, SportType (100 run, 1200 hybrid fitness) | Primary activity sync and source of labelIds. |
| `getActivityDetail` | Whole-activity summary. labelId, sportType | yes (string-encoded) | Workout Time, Distance, Average/Moving/Adjusted Pace, Best Kilometer, Average Heart Rate, **Average Cadence (spm)**, **Average Stride Length (m)**, **Average Power (W)**, Elevation Gain/Loss, Calories, Training Load, Aerobic TE, Anaerobic TE, Training Focus, Performance, Perceived Effort. "Adjusted Pace" is the grade-adjusted pace. | Per-run cadence/stride/power/GAP/TE/load summary. |
| `queryActivityLapData` | Structured lap JSON incl. running dynamics. labelId, sportType | yes (plain JSON) | See "Running dynamics" below | Best source for GCT, vertical oscillation, per-lap power/cadence/GAP. |
| `queryCustomActivityLapData` | Same columns for an arbitrary time window. labelId, sportType, startTimestamp, endTimestamp (unix s) | yes (plain JSON, key `laps`) | Same columns | Warm-up/main-set/last-N-min analysis. |
| `analyzeActivityDetail` | COROS "coach-style" narrative. labelId, sportType, focus (required in schema) | yes (string-encoded) | Conclusion and key findings as prose | Optional text for display or LLM context; not structured. |
| `queryActivityFitFileDownloadUrls` | S3 URL(s) of the original FIT. labelId+sportType or date range, limit <= 10 | yes (plain text) | `https://s3.coros.com/fit/<userId>/<labelId>.fit` | Plain HTTPS URL. FIT should hold per-second records (not verified). Quota 50 files/24h per COROS docs. |
| `downloadActivityFitFiles` | Same as above, binary resource | not tested (binary, quota) | - | Use the URL variant instead. |
| `queryDailyHealthData` | Daily overview. days (default 7) | yes (string-encoded) | Header: Resting HR, HRV Baseline. Per day: Steps, Calories, Exercise min, Floors, Stress Avg, **Sleep Summary: Total, Deep, Light, REM, Awake, Sleep HR avg/min/max**. No sleep score. | Best working source for sleep duration and stages. Arg is only `days` (365 works in one call, ~87 KB). Total includes Awake. Nap/partial nights can show a Total with all-zero stages (stored as NULL stages). Some days have no Sleep Summary (skipped). Used by `fetch_sleep_records` since Sprint 9. |
| `querySleepData` | Advertised: sleep score, main window, naps | **NO**: gateway returns `Unknown tool: invalid_tool_name / Tool not found: querySleepData` although it is in the catalog | - | No COROS sleep score available. Derive one from duration/stages/HRV. |
| `querySleepHrv` | Overnight HRV. startDate/endDate or days (max 7) | yes (string-encoded) | Per wake-up day: HRV Avg ms + label (Normal/Above normal), Normal Range lo-hi, Baseline; raw points `timestamp, hrv, status, confidence` | HRV trend and readiness. |
| `queryAvgHeartRate` | Daily avg HR. days or dates | yes | `date: 76 bpm (Min: 50, Max: 165)` | Daily HR series. |
| `queryRestingHeartRate` | Daily RHR. days | yes | `date: 56 bpm` | Recovery marker. |
| `queryStressLevel` | Daily stress. days | yes | Average Stress + label, Relaxed/Low/Medium/High durations and % | Daily stress load. |
| `queryStressTimeSeries` | Raw stress points. days (max 7) | yes | `timestamp, timezone, stress, ...` | Intraday stress (rarely needed). |
| `queryHealthCheckTimeSeries` | Latest wellness check. days (max 7) | yes | HR, HRV, Stress, Respiration, SpO2 lists, Stress Level, Resting HR | Spot check only; falls back to latest historical check. |
| `queryFitnessAssessmentOverview` | EvoLab fitness. no args | yes (string-encoded) | VO2max (46), Running Level (73), Threshold Pace (5:12 /km), 5k/10k/HM/Marathon predictions | Pace targets, race predictions, VO2max trend (poll and store daily). No threshold HR. |
| `queryTrainingLoadAssessment` | days | yes | Per day: Comment (Resuming/Maintaining/Performance/Decreasing), Short-Term Load, Long-Term Load, Load Ratio | Acute:chronic load state. |
| `queryRecoveryStatus` | no args | yes | Recovery %, Level text, Estimated Full Recovery hours | Readiness for today's plan. |
| `queryMenstruationCycles` | optional startDay/endDay | yes ("No cycle included" for this user) | phase, next period date | Optional cycle-aware coaching. |
| `queryDevices` | no args | yes | Model (COROS PACE 3 / W331), Bluetooth ID, firmware type | Device context. |
| `queryUserInfo` | no args | yes | Height, Weight, Birthday/Age, Gender | Profile defaults. |
| `queryTrainingSchedule` | startDate/endDate (default current week) | yes | Per day: workout title, source, **idInPlan**, Distance, Estimated Time, Load (TL) | Read the watch calendar; detect what the coach already pushed. |
| `queryScheduledWorkoutDetails` | date + idInPlan | not tested (needs an MCP-created idInPlan) | workout structure | Read back pushed workouts. |
| `queryTrainingPlanLibrary` | statusList [0,1,2] | yes | Plan IDs, names, status | Plan inventory. |
| `queryTrainingPlanDetails` | planId | yes | Plan ID, name, overview, status, day-by-day workouts | Inspect an active plan. |
| `queryWorkoutLibrary` | optional sportType, courseType | yes | Workout ID, name, sport, type (official/custom/mcp) | Template inventory (18 found). |
| `queryWorkoutDetails` | workoutId | yes | Template structure | Inspect a template. |

Result: 24 of 25 smoke-tested tools work; `querySleepData` fails.

## Write / side-effect tools (not smoke-tested, never called)

| Tool | Purpose | Notes |
|---|---|---|
| `createSingleWorkout` | Create ONE structured workout in the library (`course`) | Intensity as % of COROS threshold (LTHR / threshold pace) |
| `scheduleWorkout` | Put an existing library workout on a date (`workoutId`, `date`) | Today .. +90 days |
| `createScheduledWorkout` | Create and schedule a workout on one date (`date`, `course`) | Today .. +90 days; returns idInPlan |
| `updateScheduledWorkout` | Modify a scheduled standalone workout (`date`, `idInPlan`, `course`) | Cannot move dates; move/delete only in the COROS app |
| `updateWorkoutDetails` | Modify a library workout (`workoutId`, `course`) | Only MCP-editable workouts |
| `createTrainingPlan` | Save a full plan (`planInfo`, `courseList`, `phaseInfo`) | 4-16 weeks, start today..+14 days; call queryTrainingPlanLibrary first |
| `updateTrainingPlan` | Edit an in-progress MCP-created plan | Day-granular; plan deletion only in app |

## Running dynamics (where the data actually is)

Per activity, from `queryActivityLapData` / `queryCustomActivityLapData`. Parse `columns` (names plus Chinese labels), then `lapGroups[].laps[]` (custom tool: top-level `laps[]`). Real field names observed:

| Metric | Field | Unit / observed values |
|---|---|---|
| Avg cadence | `avgCadence` (and `maxCadence`) | spm, 171-182 |
| Stride length | `avgStrideLength` | cm, 84-97 (getActivityDetail shows 0.90 m) |
| Ground contact time | `groundTime` | ms, 248-285 (0 on the whole-activity group) |
| Vertical oscillation | `strideHeight` (label "vertical amplitude") | 82-89, probably mm (unverified) |
| Vertical ratio | `strideRatio` (label "vertical stride ratio") | 85-105, probably x0.1 % (unverified) |
| Running power | `avgPower` (getActivityDetail: "Average Power") | W, 199-248 |
| Grade-adjusted pace | `adjustedPace` (getActivityDetail: "Adjusted Pace") | sec/km, 340-428 |
| Left/right balance | `groundBalance` | 0.0 (needs a Running Pod) |
| Zero without pod | `formPower`, `legStiffness`, `groundReactionForce`, `groundContactAngle`, `bodyTemperature` | 0 |
| Also | `avgPace`, `avgSpeedV2`, `vertSpeed`, `avgHr`, `maxHr`, `elevGain`, `totalDescent`, `distance` (cm), `time` (s) | |

`lapGroups[].type`: `11` = workout-step laps (distance 0 for timed steps), `10` = auto per-km laps (`lapDistance` 100000 = 1 km, unit cm), `2` = another lap set, `-1` = whole activity (single row). `avgPace` is 0.0 on type-11 timed steps, so use `adjustedPace` or type 10. `sportDataDetails` was an empty list (no per-second stream over MCP).

Whole activity: `getActivityDetail` text (Average Cadence spm, Average Stride Length m, Average Power W, Adjusted Pace).

Per-second streams are not exposed by MCP; the FIT file behind `queryActivityFitFileDownloadUrls` is the route (parse with `fitparse`/`fitdecode`; not verified here).

## Coach-app needs mapping

| Need | Tool | Status |
|---|---|---|
| Run list, distance, pace, HR, calories | `querySportRecords` | yes |
| Cadence / stride / power / GAP (activity avg) | `getActivityDetail` | yes |
| GCT / vertical oscillation (per lap) | `queryActivityLapData` | yes |
| Sleep duration + stages | `queryDailyHealthData` | yes (no score) |
| Sleep score | `querySleepData` | NO (broken; COROS provides no score anywhere, `sleep_score` stays NULL) |
| Daily avg / resting HR | `queryAvgHeartRate`, `queryRestingHeartRate` | yes |
| HRV | `querySleepHrv` | yes (7 days max per call) |
| Stress | `queryStressLevel` | yes |
| VO2max / threshold pace / race predictions | `queryFitnessAssessmentOverview` | yes |
| Load and recovery | `queryTrainingLoadAssessment`, `queryRecoveryStatus` | yes |
| Push workouts / plan | `createScheduledWorkout`, `createSingleWorkout` + `scheduleWorkout`, `createTrainingPlan` | available, untested |
| Read watch calendar | `queryTrainingSchedule` | yes |

## Gaps / recommendations

1. No sleep score (tool broken): derive from duration, deep/REM share and HRV; re-test `querySleepData` periodically.
2. Text outputs need regex parsing and a double `json.loads`; write one parser per tool and unit-test against `scripts/smoke_output/*.txt` fixtures.
3. Threshold HR, max HR and HR zones are not returned by any tool; take them from the profile or estimate from observed max HR.
4. Per-second data only via the FIT URL; useful for cadence/power drift and decoupling analysis.
5. HRV, stress and health-check queries are limited to 7 days per call; chunk backfills.
6. Nothing can be moved or deleted from MCP (app only). Before pushing, read `queryTrainingSchedule` to avoid duplicates, and store the returned `idInPlan` in coach.db for later updates.
7. Balance, leg stiffness and force fields need a Running Pod (zeros on PACE 3 alone). Vertical oscillation units still need verification.
8. Each CLI call costs 4-5 s; batch, cache, and poll fitness/load once a day.

## Official sources

- COROS MCP GitHub (official, coroslab): https://github.com/coroslab/COROS-MCP (30+ tools; HTTP OAuth endpoint `https://mcp.coros.com/mcp` for ChatGPT/Claude/Codex; skill install `npm install -g coros-mcp` for OpenClaw/Workbuddy/Hermes; limits: FIT 50 files/24h, stress series 7 days, scheduling today..+90 days, plans 4-16 weeks starting within 14 days; no moving/removing scheduled workouts or deleting plans)
- COROS announcement page: https://coros.com/stories/coros-metrics/c/mcp-testing (bridge to training history; endpoint consolidated to one URL on 2026-05-19)
- Independent review: https://the5krunner.com/2026/05/13/coros-mcp-ai-data/ (launch-time; said running dynamics, per-second streams and calendar push were absent. Our tests show lap-level GCT/vertical oscillation and scheduling tools now exist, so it is outdated.)
- Unofficial, reverse-engineered alternatives (different API): https://github.com/cygnusb/coros-mcp, https://github.com/ntmill/coros-mcp
