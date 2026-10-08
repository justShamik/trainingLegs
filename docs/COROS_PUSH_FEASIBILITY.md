# Pushing the training plan to the COROS calendar: feasibility

> **Status: built 2026-10-09** ("Send to COROS" on the plan page, `/plan/push`). Implementation:
> `app/coros_push/workouts.py` (session -> course), `app/coros_push/service.py` (preview, duplicate check,
> confirmed create/update, one app-owned workout per date in `coros_pushes`), `app/web/push_routes.py`.
> Differences from the plan below: per-session `createScheduledWorkout` only (no `createTrainingPlan`);
> warm-up/recovery/cool-down use the watch's HR zones; LTHR Test = 15 min + 10 min + 20 min + 10 min steps.
> Not yet verified against the live account: the exact `createScheduledWorkout` reply (the idInPlan is parsed
> from it, else found by re-reading that day's calendar).

Researched 2026-09-29. Sources: `~/.coros-mcp-skill-gateway-ts/us/tool-catalog.json` (full descriptions and schemas), the official repo (https://github.com/coroslab/COROS-MCP, as summarised in COROS_CAPABILITIES.md), and read-only calls (`queryTrainingSchedule`, `queryDevices`, `queryTrainingPlanLibrary`, `queryWorkoutDetails`, `queryScheduledWorkoutDetails`). No write tool was called.

## 1. Verdict

**Feasible: yes, for run sessions, with limits.** Every non-rest session (Easy Aerobic, Recovery, Threshold, VO2max, Long Run, Time-on-Feet, Vert) can be expressed as a structured COROS running workout and placed on its date with `createScheduledWorkout`. Structured workouts with HR or pace targets sync to the PACE 3 (COROS W331, the only bound device) through the normal COROS app calendar sync. Not verified: that this specific workout renders on the watch, since that needs a real write. The catalog says nothing about per-device support.

The blocker is irreversibility. Nothing pushed can be moved or deleted through MCP. The design must therefore be preview-first, explicit-confirm and idempotent.

## 2. Write tool reference

| Tool | Required args | Notes |
|---|---|---|
| `createScheduledWorkout` | `date` (yyyyMMdd string), `course` | Creates one workout on one date. Nothing goes into the library. Returns `idInPlan`. One call per workout. Not idempotent. Other workouts on the same day do not block it and are listed in the result. |
| `createSingleWorkout` | `course` | Library template only, no date. Rest (4) is not allowed. |
| `scheduleWorkout` | `workoutId` (decimal string), `date` | Copies a library workout onto a date. The same library workout already on that day is not added twice. Any other workout is added. |
| `createTrainingPlan` | `planInfo{planName, planOverview, planStartDate, totalWeeks}`, `courseList[]`, `phaseInfo{periodization[]}` | See section 2.3. |
| `updateTrainingPlan` | `planInfo{planId,...}` | Only for an in-progress plan with recordRole=execution and editable=true. Replaces whole days. |
| `updateScheduledWorkout` | `date`, `idInPlan` (string), `course` | Full replacement. Call `queryScheduledWorkoutDetails` first. Only for editable=true items. Cannot move dates, cannot delete. |
| `updateWorkoutDetails` | `workoutId`, `course` | Library template only. Scheduled copies are independent and unchanged. |

### 2.1 Course model (identical across tools)

- `course` fields: `courseName` (required, at most 100 chars), `courseDescription` (required, non-empty), `sportType` (required), `sections[]` (required, non-empty; empty array for rest courses in plans). Do not send `dayNo` (except in plan `courseList`) or `strengthBodypart`.
- `sportType`: 1 running, 2 cycling, 4 rest (training plans only), 5 trail running. No strength or swim.
- Plain section: `sectionType` (1 warmup, 2 training, 3 recovery, 4 cooldown), `targetType`, `targetValue`, plus intensity fields.
- `targetType`: 1 distance in metres, 2 time in seconds, 3 climb in metres (trail only), 4 free/lap-button (omit `targetValue`; only if explicitly wanted). Running allows 1/2/4. Trail running allows 1/3/4 (no time). Values are positive integers.
- Interval group: `{"intervalGroup": true, "repeats": 1-20, "sets": [plain sections with sectionType 2 or 3]}`. No nesting. The container has no target or intensity fields. Each member has its own.
- Intensity, per plain section. Running allows `intensityType` 1 (HR), 2 (pace) or 4 (power). Type 3 (% effort threshold pace) is trail only. Choose exactly one format:
  - (a) `sectionIntensity` zone 1-6.
  - (b) `intensityPercentStart/End`: %LTHR for HR (20-120, start < end), %threshold pace for pace (20-140). Not for power.
  - (c) `intensityValueStart/End` absolute: HR 30-240 bpm, pace 120-1499 **seconds per km** (smaller is faster; either order accepted; equal is allowed), running power 10-2000 W. Both endpoints are required.
  - Omit all intensity fields only if no target is wanted. Never send 0.
  - Cadence targets do not exist.
- Text is shown to the athlete exactly as written. Plain language only (no field names or enum numbers). Zone 2, LTHR and similar terms are fine.

### 2.2 Dates and idempotency

- `date` must be from today to today+90 inclusive, in the COROS profile timezone (UTC if unknown). Past dates are rejected.
- `createScheduledWorkout` will happily create a second identical workout. `scheduleWorkout` de-duplicates only when the same library workout is already on that day. Idempotency is therefore our responsibility (section 4).
- The result returns `idInPlan`, which should be stored. The catalog says not to show it to the user.
- Not possible over MCP: moving, removing or completing scheduled workouts, deleting plans or workouts, quitting a plan. All of these are done in the COROS app.

### 2.3 Training plan tool

- `totalWeeks` 4-16 natural Monday-Sunday weeks. The plan always ends on the Sunday of the last week.
- `planStartDate` must be within today to today+14. The first week is partial if the start is not a Monday.
- `dayNo` 0 is the start date. Days without a course are rest days. The last week needs at least one workout.
- `phaseInfo.periodization` is required: `{phaseType 1-6, startDate, endDate, durationWeeks}`. The first phase starts on planStartDate, later phases start on a Monday, and all phases end on a Sunday. Weeks must sum to `totalWeeks`.
- `planName` is at most 90 English characters, `planOverview` at most 800.
- Existing or overlapping plans do not block creation, but the tool asks that the user be told of the overlap.
- Up to 40 workouts per day. One session is one course, so do not split warm-up, main set and cool-down into separate courses.
- The created plan cannot be deleted through MCP, only in the app. It can be edited through `updateTrainingPlan`, if it appears with editable=true.

## 3. The user's account, read-only (2026-09-29)

- Device: one bound device, COROS PACE 3 (W331).
- `queryTrainingSchedule` for 29 Sep to 29 Oct returns only two items:
  - 2026-09-29 "Countdown Intervals" (standalone, idInPlan 122, 9.44 km, 1:10:00, 122 TL).
  - 2026-09-30 "Aerobic Power Run" (standalone, idInPlan 121, 10.00 km, 1:09:25, 145 TL).
  - Pushing onto these two dates would add a second workout. The schedule listing is the source of truth for the duplicate check.
- `queryTrainingPlanLibrary`: one plan is in progress, "P10061" (execution record, 2026-07-20 to 2026-10-04, 10 weeks, editable via MCP: no). It overlaps the first days of our 5-week plan. A newly created COROS plan would overlap it, so use per-session scheduling instead.
- Library: 18 workouts (mostly official templates). Their read-back shows the format we must produce. Example course JSON: `{"sectionType":1,"targetType":2,"targetValue":300}` and `{"intervalGroup":true,"repeats":3,"sets":[...]}`. Existing items report editable=no because of empty descriptions or intensityType 3. Ours will be editable because we always set a description and use only types 1/2.
- Threshold pace 5:12 /km (`queryFitnessAssessmentOverview`). This can back %-of-threshold targets, but the app currently emits absolute targets.

## 4. Mapping our sessions to COROS

Our fields: `day_of_week`, session date (derived from the plan start; `plan_sessions` currently has no date column, so compute it), `session_type`, `distance_km`, `duration_min`, `target_pace_or_hr`.

Parse `target_pace_or_hr` with a regex into `hr_lo/hr_hi` (bpm) and `pace_lo/pace_hi` (mm:ss per km converted to seconds). Both are present in every current string.

| session_type | COROS | Structure |
|---|---|---|
| Rest | Nothing. | Never pushed. A Rest course is only meaningful in `createTrainingPlan`. |
| Easy Aerobic, Recovery | sportType 1 | One training section (2). `targetType` 1 with `distance_km*1000` m, or 2 with `duration_min*60` s. HR range from the string, `intensityType` 1, `intensityValueStart/End` (e.g. 130-145). Optionally a 5 min warmup and 5 min cooldown at the same HR range. Keep simple. |
| Long Run | sportType 1 | Same as easy: one distance-based section. HR range if the string has one. |
| Time-on-Feet | sportType 1 | One time-based section (`targetType` 2) with the HR range. |
| Vert | sportType 1 (or 5) | No elevation data in the plan string. Use sportType 1 with a distance target and HR range. Trail (5) only allows distance or climb targets. |
| Threshold | sportType 1 | Warmup 10 min (time, HR range from easy zone). Interval group `repeats` = N of {work: 8 min at threshold pace range in s/km; recovery: 2 min easy}. Cooldown 10 min. Choose N so total time is about `duration_min` (for example 60 min gives 4x(8+2)). Pace targets: `intensityType` 2, `intensityValueStart` = faster value, `intensityValueEnd` = slower value (e.g. 315/330). Descriptions explain it. |
| VO2max | sportType 1 | Warmup 10-15 min, group of 5x(3 min work at pace range / 2-3 min recovery), cooldown 10 min. If the string carries no pace, use HR or zone 5 (`sectionIntensity` 5). |

Encoding rules: pace in whole seconds per km (5:15 = 315). Distance in metres and time in seconds, all integers. HR in bpm within 30-240. Never send the percent fields unless we deliberately choose %LTHR or %threshold pace, and never zero. Reject the session with a clear preview error (not a partial push) if any value falls outside these bounds.

`courseName` example: "Threshold 4 x 8 min". `courseDescription` example: "Warm up easy. Run each 8 minute block at 5:15 to 5:30 per km (Zone 4, about 158 to 170 bpm) with 2 minutes easy jogging between. Cool down easy." The description must be non-empty and plain.

### 4.1 Which tool

| | `createScheduledWorkout` per session (recommended) | `createTrainingPlan` for the 5 weeks |
|---|---|---|
| Pros | Granular. `updateScheduledWorkout` can fix single sessions afterwards. Each `idInPlan` is stored. No overlap with plan P10061. Works for any horizon up to 90 days. | One call, appears in the app as a plan with phases. Day-granular `updateTrainingPlan` allows replacing whole days, so regeneration is partly possible. |
| Cons | About 4-5 s per call and 4-5 sessions per week, so about 20-25 calls. No dedupe. Some calls may fail midway, so track per-row state. | Requires `totalWeeks` 4-16, start within 14 days, and phaseInfo. It overlaps the running plan through 2026-10-04. Cannot be deleted through MCP. `updateTrainingPlan` works only if it later shows editable=true. A plan that is later regenerated leaves an orphan plan behind. |

Regeneration after pushing: a regenerated plan cannot delete what was pushed. Choices are (1) update changed days with `updateScheduledWorkout` (same date, only if editable and the day is not completed), (2) tell the user which pushed sessions are now stale and must be removed in the COROS app, (3) push only future sessions the user opts into. Never auto-repush.

## 5. Safe UX

1. **Preview page** `/plan/push-preview`. It lists exactly what will be created. For each session: date, name, description, section table (step, target, value), and the raw JSON in a collapsible block. It shows the count of workouts and the account timezone note. Statuses per row: `will create`, `already pushed`, `duplicate on calendar`, `date out of range (past or >90 days)`, `invalid (reason)`, `rest (skipped)`.
2. **Dry-run** is the default. The preview builds the JSON and validates locally without calling any write tool. It does read `queryTrainingSchedule` for the window to flag duplicates and the existing items.
3. **Explicit confirm**: the `/plan/push` POST needs a checkbox "I understand pushed workouts can only be moved or deleted in the COROS app", a preview token/hash of the payload (rejects if the plan changed since preview), and lets the user untick rows. Optionally offer a first-week-only push.
4. **Idempotency** through table `plan_session_push` (section 6). Before each create: skip if a row exists with status `pushed` for the same `session_id` and identical payload hash. If the hash differs, mark it `stale` and offer `updateScheduledWorkout` (needs `idInPlan`).
5. **Duplicate detection** against the live calendar: read `queryTrainingSchedule` (start=today, end=last session date) and match date + courseName (we use a stable naming scheme). Any same-day item is shown as an FYI (e.g. the 29 and 30 Sep items above), and a same-name item blocks that row.
6. **Failure handling**: write a row `pending` before each call and `pushed` or `failed` after. A crash between the call and the DB write means the next preview's calendar check reveals the item and the row is reconciled instead of re-created. Stop on the first error class that is not row-specific (auth, rate limit).
7. **Regenerate/discard**: `/plan/generate` and `/plan/discard` show a warning if `plan_session_push` has `pushed` rows for that plan ("N workouts are on your COROS calendar and must be removed in the COROS app"). The push rows stay as an audit log and are marked `orphaned`.

## 6. Argument JSON examples

Easy run (distance 8 km, HR 130-145, plain step):

```json
{
  "date": "20261001",
  "course": {
    "courseName": "Easy Aerobic Run 8 km",
    "courseDescription": "Relaxed conversational run in Zone 2. Keep your heart rate between 130 and 145 bpm (roughly 6:00 to 6:30 per km). Ease off on hills to stay in range.",
    "sportType": 1,
    "sections": [
      {
        "sectionType": 2,
        "targetType": 1,
        "targetValue": 8000,
        "intensityType": 1,
        "intensityValueStart": 130,
        "intensityValueEnd": 145
      }
    ]
  }
}
```

Threshold session (60 min: 10 min warmup, 4 x 8 min at 5:15-5:30 per km with 2 min easy, 10 min cooldown):

```json
{
  "date": "20261002",
  "course": {
    "courseName": "Threshold 4 x 8 min",
    "courseDescription": "Warm up easy for 10 minutes. Then run four 8 minute blocks at threshold pace, 5:15 to 5:30 per km (Zone 4, about 158 to 170 bpm), with 2 minutes of easy jogging between blocks. Cool down easy for 10 minutes.",
    "sportType": 1,
    "sections": [
      {"sectionType": 1, "targetType": 2, "targetValue": 600,
       "intensityType": 1, "intensityValueStart": 130, "intensityValueEnd": 145},
      {"intervalGroup": true, "repeats": 4, "sets": [
        {"sectionType": 2, "targetType": 2, "targetValue": 480,
         "intensityType": 2, "intensityValueStart": 315, "intensityValueEnd": 330},
        {"sectionType": 3, "targetType": 2, "targetValue": 120,
         "intensityType": 1, "intensityValueStart": 110, "intensityValueEnd": 140}
      ]},
      {"sectionType": 4, "targetType": 2, "targetValue": 600,
       "intensityType": 1, "intensityValueStart": 110, "intensityValueEnd": 140}
    ]
  }
}
```

Rest day: no call. `session_type == "Rest"` is filtered out before the preview. (In a training plan you would omit the day or send `{"sportType":4,"courseName":"Rest","courseDescription":"Recovery day","sections":[]}`, but the per-session route does not use it.)

Table for idempotency:

```sql
CREATE TABLE IF NOT EXISTS plan_session_push (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,           -- plan_sessions.id
  plan_id TEXT NOT NULL,
  session_date TEXT NOT NULL,         -- yyyyMMdd
  course_name TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL,               -- pending|pushed|failed|stale|orphaned
  coros_id_in_plan TEXT,
  error TEXT,
  pushed_at TIMESTAMP,
  UNIQUE(session_id, payload_hash)
);
```

## 7. Risks

- Irreversible writes (no delete or move over MCP). Mitigation: preview, confirmation, opt-in per row, small first push.
- Duplicates: `createScheduledWorkout` is not idempotent. Mitigation: local table plus live calendar check.
- Shown text: names and descriptions appear in the app verbatim, so no internal labels.
- Overlap with the running COROS plan P10061 (until 2026-10-04) and the two standalone workouts on 29 and 30 Sep. Same-day items are not blocked and will stack on the watch.
- Timezone: dates are resolved in the COROS profile timezone, which may differ from local; a "today" push at night could be rejected as past.
- Absolute HR and pace values depend on our own zone estimate. COROS zones (LTHR, threshold pace 5:12) may differ; if we send absolute values there is no drift, but the watch zone labels in the app may not match our text.
- Parsing risk of `target_pace_or_hr`: strings are LLM-influenced. Validate strictly and refuse to push what cannot be parsed. Do not guess.
- Each call takes about 4-5 s and the CLI can time out at 60 s. Plan for 25 calls (about 2 minutes) in a background task with progress, not a synchronous request.
- Device rendering not verified without a real write. First push should be a single session the user then checks on the watch.

## 8. Implementation plan

1. `app/mcp_client/coros_push.py`
   - `parse_target(text) -> Targets(hr, pace)`.
   - `build_course(session) -> dict | None` (None for Rest), pure functions per session type, plus `validate_course(course)` implementing the bounds above.
   - `CorosPushService(client)`: `preview(plan_id)` (reads calendar, builds rows and statuses) and `push(plan_id, session_ids, preview_hash)`; the client dependency exposes `query_schedule(start, end)` and `create_scheduled_workout(date, course)` and is faked in tests. Extend `CorosMCPClient` with these two thin methods over `_call_cli_tool`, parsing `idInPlan` from the result text.
2. DB: add `plan_session_push` to `app/data/schema.sql` (and migration in `db.py`), with helpers in `queries.py`.
3. Routes in `app/web/routes.py`: `GET /plan/push-preview` (dry run, read-only) and `POST /plan/push` (requires confirm flag and preview hash, runs sequentially and records each row). Add warnings to `/plan/generate` and `/plan/discard`.
4. UI: "Send to COROS" button on the plan page, preview template with per-row checkboxes, warning banner, result summary (created, skipped, failed).
5. Tests with a fake client: mapping per session type (golden JSON for the two examples), pace/HR parsing and out-of-range rejection, Rest never pushed, date window (past and >90 days), idempotent re-push (no second create), duplicate calendar detection, partial-failure recovery, preview hash mismatch, regenerate warning. No test touches the real gateway.
6. Manual acceptance: push one easy session for tomorrow, check `queryScheduledWorkoutDetails` reports it editable, check the watch, then enable the full push.
