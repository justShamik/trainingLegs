# Heart-Rate Zones From a Field Test: Research, Protocol and App Proposal

Status: **built (2026-10-09)** - see "Implementation status" at the end of section 8. Sections 1-7 are the research it follows.
Date: 2026-10-08. Athlete context: recreational marathon/ultra runner in Delhi NCR, COROS PACE 3, age 33 (from `queryUserInfo`), COROS EvoLab threshold pace 5:12 /km (from `queryFitnessAssessmentOverview`).

---

## 1. Summary and recommendation

**Is there a meta-study?** Not for the exact question. I could not find a systematic review or meta-analysis of *solo field tests for lactate-threshold heart rate (LTHR)* in runners. What exists:

- A meta-analysis for **age-predicted HRmax** (Tanaka et al., 2001). It gives a better formula than 220 - age, but individual errors are large: limits of agreement of about ±18-24 bpm in a 2025 validation (Martin et al., 2025). That is not good enough for setting zones.
- A meta-analysis for **HRV-derived thresholds** (DFA-alpha1; Tanner, Millet & Bourdillon, 2024). Group agreement with lab thresholds is good. However, it needs beat-to-beat RR data from a chest strap, and the COROS FIT file does not contain RR data (see section 7). It is not usable with this setup.
- **Single validation studies** of field tests. The best supported solo running test is the **30-minute time trial**. In McGehee, Tanner & Houmard (2005), it did not differ from lab LT heart rate, with a standard error of the estimate (SEE) of 8.0 bpm. Narrative reviews explain why the "threshold" depends on how it is defined (Faude et al., 2009; Jamnick et al., 2020).
- **Rejected methods.** The Conconi HR-deflection test is not valid in runners (Jones & Doust, 1997). Age formulas are too imprecise for an individual.

**Recommendation: one protocol.** Run a **30-minute solo time trial on a flat loop or track, in the coolest conditions available**. Compute **LTHR = mean heart rate over minutes 10:00-30:00**, using the per-second FIT stream with artifact cleaning. Enter it in COROS as **Threshold HR** and use COROS's **Lactate Threshold zone model** (EvoLab's default, 6 zones). Retest every 6-8 weeks or at the start of each training block. Treat the result as ±5-8 bpm, not as an exact number.

For HRmax (needed only if you use the Max HR or HR Reserve models), use the highest *clean* HR seen in a race or hard test. Never use an age formula except as a sanity check.

---

## 2. Evidence table

| # | Method | Study (verified citation) | Design / n | Agreement with lab reference | Verdict for this user |
|---|---|---|---|---|---|
| 1 | **30-min solo time trial** (HR of the TT as LTHR estimate) | McGehee JC, Tanner CJ, Houmard JA (2005). *A comparison of methods for estimating the lactate threshold.* J Strength Cond Res 19(3):553-558. doi:[10.1519/15444.1](https://doi.org/10.1519/15444.1) | 27 competitive distance runners/triathletes. Criterion: lab LT at 4.0 mmol/L. Compared VDOT, 3200 m TT, 30-min TT and Conconi | 30-min TT HR **not significantly different from criterion, SEE 8.0 bpm**. Speed SEE 0.21 m/s. Conconi did worse | **Recommended.** Single study, small n, criterion is a fixed 4 mmol/L (roughly LT2/MLSS territory, not LT1) |
| 1b | Friel's version of the 30-min TT (lap at 10 min, average the last 20 min) | Friel J. *Joe Friel's Quick Guide to Setting Zones.* TrainingPeaks. [link](https://www.trainingpeaks.com/learn/articles/joe-friel-s-quick-guide-to-setting-zones/) | Coaching protocol, not a peer-reviewed validation | No published agreement statistics that I could verify | Use as the **computation rule**: dropping the first 10 min removes HR lag |
| 2 | **Age formula: Tanaka** HRmax = 208 - 0.7 x age | Tanaka H, Monahan KD, Seals DR (2001). *Age-predicted maximal heart rate revisited.* J Am Coll Cardiol 37(1):153-156. doi:[10.1016/S0735-1097(00)01054-8](https://doi.org/10.1016/S0735-1097(00)01054-8) | Meta-analysis of 351 studies (18,712 subjects) plus lab cross-validation (n=514) | Better than 220 - age at the group level, especially in older adults | Sanity check only. For age 33: **185 bpm** |
| 3 | Age formula: Gellish HRmax = 207 - 0.7 x age | Gellish RL et al. (2007). *Longitudinal modeling of the relationship between age and maximal heart rate.* Med Sci Sports Exerc 39(5):822-829. doi:[10.1097/mss.0b013e31803349c6](https://doi.org/10.1097/mss.0b013e31803349c6) | 132 people, 908 graded exercise tests over 25 years | Group-level fit | Sanity check only: **184 bpm** |
| 3b | Age formula: Nes HRmax = 211 - 0.64 x age | Nes BM et al. (2013). Scand J Med Sci Sports. doi:[10.1111/j.1600-0838.2012.01445.x](https://doi.org/10.1111/j.1600-0838.2012.01445.x) | HUNT cohort | Group-level fit | Sanity check: **190 bpm** |
| 3c | Validation of the age formulas | Martin, Lindsey, Gerrity, Ambegaonkar (2025). *Exploratory analysis of the accuracy of age-based maximal heart rate equations across cardiorespiratory fitness levels.* PLOS ONE. doi:[10.1371/journal.pone.0335842](https://doi.org/10.1371/journal.pone.0335842) | 230 adults with maximal tests. Seven equations compared | Mean bias -3 to +6 bpm, but **limits of agreement about ±18-24 bpm**. Tanaka, Gellish and Arena were best, but "none demonstrated high individual level accuracy" | **Do not set zones from age formulas** |
| 4 | Fixed %HRmax anchors for LT1/LT2 | Nuuttila OP, Kaikkonen P, Sievänen H, Vasankari T, Kyröläinen H (2025). *The accuracy of fixed intensity anchors to estimate lactate thresholds in recreational runners.* Eur J Appl Physiol. doi:[10.1007/s00421-025-05748-8](https://doi.org/10.1007/s00421-025-05748-8) | 165 recreational runners, incremental treadmill test | With *measured* HRmax, HR mean absolute error was LT1 4.9-7.4 bpm and LT2 2.8-5.2 bpm. With *estimated* max, errors rose to 8.4 bpm (LT1) and 6.7 bpm (LT2) | %HRmax zones are only acceptable if HRmax is measured. Supports anchoring zones on a measured value |
| 5 | **Conconi HR deflection** | Jones AM, Doust JH (1997). *The Conconi test is not valid for estimation of the lactate turnpoint in runners.* J Sports Sci 15(4):385-394. doi:[10.1080/026404197367173](https://doi.org/10.1080/026404197367173) | Runners, incremental test | Deflection appeared at a systematically higher intensity than the lactate turnpoint, around 95% HRmax. Judged invalid | **Avoid** |
| 6 | **HRV / DFA-alpha1 thresholds** | Tanner V, Millet GP, Bourdillon N (2024). *Agreement between heart rate variability-derived vs. ventilatory and lactate thresholds: a systematic review with meta-analyses.* Sports Med Open 10:109. doi:[10.1186/s40798-024-00768-8](https://doi.org/10.1186/s40798-024-00768-8) | 50 studies, 1,160 subjects | HRVT1 vs LT1/VT1: SMD 0.08, r 0.84. HRVT2 vs LT2/VT2: SMD -0.06, r 0.85. DFA-a1 HRVT1: r 0.86. But I² 89-93% and wide prediction intervals, and algorithmic detection did worse than visual | Promising but **not feasible**: needs RR intervals from a chest strap, and the COROS FIT has no `hrv` messages |
| 6b | DFA-a1 = 0.75 as the aerobic threshold | Rogers B, Giles D, Draper N, Hoos O, Gronwald T (2021). Front Physiol 11:596567. doi:[10.3389/fphys.2020.596567](https://doi.org/10.3389/fphys.2020.596567). Update: Rogers & Gronwald (2022) Front Physiol 13:879071. doi:[10.3389/fphys.2022.879071](https://doi.org/10.3389/fphys.2022.879071) | Incremental treadmill tests | Crossing a1 = 0.75 was closely associated with VT1 | Same limitation as row 6 |
| 7 | **Smartwatch automatic LTHR** (includes COROS PACE 3) | Lu C, Cui W, Zhu Z, Wu Y, Xing Q, Pan B, Shen Y (2025). *Validity of smartwatch-derived estimates of lactate threshold heart rate and pace compared to graded exercise testing.* Front Physiol 16:1621996. doi:[10.3389/fphys.2025.1621996](https://doi.org/10.3389/fphys.2025.1621996) | 100 recreational runners. COROS subgroup n=17. Reference: modified Dmax | COROS LTHR: test success rate 47%, **MAE 8.93 bpm (MAPE 5.95%)**, no significant mean difference. Pace was overestimated by all watches (COROS MAE 1.93 km/h). Overall r 0.13-0.67 | COROS's own Running Fitness Test is about as accurate as the 30-min TT for HR, but it failed in more than half of the tests. Use it as a cross-check |
| 8 | Talk test | Reed JL, Pipe AL (2014). *The talk test: a useful tool for prescribing and monitoring exercise intensity.* Curr Opin Cardiol 29(5):475-480. doi:[10.1097/HCO.0000000000000097](https://doi.org/10.1097/HCO.0000000000000097) | Narrative review, mostly clinical and general populations | Last "comfortable speech" stage is close to VT1 | Useful daily cross-check for the top of Zone 2. Not a number generator |
| 9 | Optical vs chest-strap HR | Gillinov S et al. (2017). *Variable accuracy of wearable heart rate monitors during aerobic exercise.* Med Sci Sports Exerc 49(8):1697-1703. doi:[10.1249/MSS.0000000000001284](https://doi.org/10.1249/MSS.0000000000001284) | ECG reference, several devices (COROS not included) | Chest strap rc = 0.99. Wrist devices rc 0.52-0.80 and varied by activity | Use a chest strap for the test if you have one |
| 10 | Heat and cardiovascular drift | Wingo JE, Lafrenz AJ, Ganio MS, Edwards GL, Cureton KJ (2005). *Cardiovascular drift is related to reduced maximal oxygen uptake during heat stress.* Med Sci Sports Exerc 37(2):248-255. doi:[10.1249/01.MSS.0000152731.33450.95](https://doi.org/10.1249/01.MSS.0000152731.33450.95) | Lab study | Heat makes HR drift upward and lowers capacity during prolonged exercise | A hot test inflates HR at a given effort and changes the LTHR you measure. Control the conditions |
| 11 | Background: threshold concepts | Faude O, Kindermann W, Meyer T (2009). *Lactate threshold concepts: how valid are they?* Sports Med 39(6):469-490. doi:[10.2165/00007256-200939060-00003](https://doi.org/10.2165/00007256-200939060-00003). Jamnick NA et al. (2020). *An examination and critique of current methods to determine exercise intensity.* Sports Med 50:1729-1756. doi:[10.1007/s40279-020-01322-8](https://doi.org/10.1007/s40279-020-01322-8) | Reviews | Different lab definitions of "threshold" give different values. No method is gold-standard | Explains why even a lab LTHR carries ±several bpm of uncertainty |

**Not verified / not included:** critical speed (it gives a pace, not a HR, and I did not verify a HR-agreement study), "20-min test x 0.95" for running (adapted from cycling FTP, and I found no running validation), and the 3-stage COROS Running Fitness Test algorithm (proprietary).

---

## 3. Recommended protocol: the 30-minute LTHR time trial

**Equipment.** COROS PACE 3. Use a chest strap (COROS HRM or any BLE/ANT+ strap) if you have one. Otherwise wear the watch snug, two fingers above the wrist bone. Use a 400 m track or a flat loop of 1-2 km with no traffic lights. Use the GPS Run (outdoor) mode, or Track Run on a track.

**When.**
- Use the coolest window available. In Delhi NCR that is before sunrise from October to March. In April-September, run indoors on an AC treadmill at a 1% incline, or wait for a cool, low-humidity morning.
- Target an air temperature of 25 °C or lower and a dew point below about 18 °C. Note the temperature. The FIT `session.avg_temperature` is a wrist reading biased by skin heat, so record the weather separately.
- Have at least 2 easy days or rest days beforehand, no long run in the previous 48 h, and normal sleep. Avoid days when HRV or recovery is flagged low in the app.
- Avoid high-AQI days (above about 200). Breathing load matters on a maximal-ish effort.
- Eat normally. Drink 500 ml of fluid 1-2 h before. Avoid caffeine above your usual dose because it shifts HR.

**Structure** (if implemented, build it as a COROS structured workout so the watch auto-laps each step):
1. **Warm-up, 15 min:** 10 min easy (conversational), then 3 x 20 s strides at about 5 km effort with 60-70 s easy jog between, then 2 min easy.
2. **Test, 30:00 continuous, solo** (no pacer, not a race):
   - Pacing cue: the best *even* effort you can sustain for exactly 30 minutes, about 10 km to 15 km race effort, RPE 7-8/10.
   - For this athlete, COROS threshold pace is 5:12 /km. Start at about 5:15-5:25 /km for the first 5 min, settle, and only push in the last 5-8 min if there is clearly something left.
   - Do not sprint the start. The first 10 min are excluded from the calculation, but a hot start ruins the next 20.
   - Do not stop. Do not pause the watch. If you must stop (traffic, a lace), keep the timer running and note it. Stops longer than 15 s invalidate the test (see the quality rules).
   - **Press LAP at exactly 10:00.** If built as a structured workout, use a 10:00 step plus a 20:00 step, which gives the same split automatically.
3. **Cool-down:** 10 min easy.

**Validity checks after the run** (the app should automate these):
- Even pacing: pace over minutes 10-30 within ±5% of its mean.
- HR plausible: no dropouts and no cadence lock (HR equal to cadence for long stretches, a common optical-sensor failure at about 170-180 spm).
- The final 20 minutes contain at least 1150 s of valid HR samples.

**How often.**
- Do one test at the start of each training block, then every **6-8 weeks**.
- Also retest after a long break (more than 2 weeks) or when easy-run HR at a fixed pace has shifted by 5 bpm or more for 2 weeks.
- Do not test within 10 days of a goal race or in a heavy-mileage week.
- Optional: repeat once within 7-14 days. If the two results are within 3 bpm, average them. If not, take the one run in better conditions.

**What to avoid.**
- Group runs or races used as the test (both raise HR).
- Hills or wind.
- Heat or high humidity.
- Testing after a long run (durability shifts HR).
- Conconi or "deflection" tests.
- Age formulas.
- The "20 min x 0.95" shortcut.
- Changing HR sensors between tests (wrist vs strap).

---

## 4. Computation

### 4.1 Data source (preference order)

1. **Per-second FIT stream (preferred).** Get the URL from `queryActivityFitFileDownloadUrls(labelId, sportType=100)`, then download and decode the `record` messages (`timestamp`, `heart_rate`, `speed`/`enhanced_speed`, `distance`, `cadence`, `enhanced_altitude`). This is the only route to artifact cleaning. The COROS quota is 50 FIT files per 24 h, which is ample for one test.
2. **Window average without the FIT.** Call `queryCustomActivityLapData(labelId, sportType, startTimestamp = t0 + 600, endTimestamp = t0 + 1800)`, where `t0` is the start time of the test step. It returns `avgHr`/`maxHr` for exactly that window as integers, with no cleaning. This is a good fallback or cross-check.
3. **Workout-step laps.** `queryActivityLapData` lap group `type: 11` (workout steps) or `type: 2` (manual laps) gives `avgHr` per step. If the test is a 10:00 step plus a 20:00 step, the 20:00 step's `avgHr` is the Friel LTHR directly.

### 4.2 Locate the test window
- If the activity came from the pushed "LTHR Test" workout, take the type-11 lap whose `time` is about 1200 s and which follows a lap of about 600 s. Its `totalLength` minus `time` gives the offset from the activity start.
- Otherwise, search the FIT for the 30-min window with the highest mean speed and low speed variance, or use the manual LAP pressed at 10:00.

### 4.3 Cleaning (applied to the 1200 s analysis window, minutes 10-30 of the test)
1. **Resample** to a 1 Hz grid on `timestamp`. The sample FIT is already strictly 1 s (3172 of 3172 intervals were 1.0 s).
2. **Pauses and stops.** Find gaps of more than 2 s between timestamps, or `speed < 1.5 m/s` for 5 s or more. Exclude those samples. If the excluded total is over 15 s in a single stop or over 60 s overall, mark the test **invalid**.
3. **Dropouts.** `heart_rate` missing or 0: linear-interpolate gaps of 5 s or less and drop longer gaps. If more than 5% of the window is missing, mark the test low-confidence.
4. **Spikes.** Flag a sample when |HR - rolling 15 s median| exceeds 10 bpm, or when |delta HR| exceeds 8 bpm/s. Replace it with the rolling median.
5. **Cadence lock (optical only).** Flag when |HR - cadence x 2| is 3 or less, or |HR - cadence| is 3 or less, for more than 30 s. FIT `cadence` is per leg (87 = 174 spm). Warn when more than 10% of the window is flagged.
6. **Physiological bounds:** 40-220 bpm.

### 4.4 Formulas
- **LTHR = round(mean(HR_clean[t0+600 : t0+1800]))**, the Friel rule.
- **Drift and pacing diagnostics** (reported only, not used to adjust):
  - HR drift = mean HR in minutes 20-30 minus mean HR in minutes 10-20. Pace change = the same comparison for speed.
  - A rise of 3-6 bpm at a steady pace is normal for an all-out effort. A rise above 8 bpm with a falling pace suggests heat or dehydration or a too-fast start, so lower the confidence.
- **Confidence label:**
  - *Good*: chest strap, ≤ 25 °C, pace CV ≤ 5%, missing HR ≤ 2%, no cadence lock, drift ≤ 6 bpm.
  - *Fair*: one criterion missed.
  - *Poor*: two or more missed, or an invalid stop. In that case do not recommend changing COROS.
  - Always show the result as **LTHR ± 8 bpm (field-test standard error, McGehee 2005)**.
- **Cross-checks shown next to the result:**
  - COROS LTHR if available, from watch settings or the Running Fitness Test (Lu et al., 2025: MAE about 9 bpm).
  - The highest observed HRmax. LTHR is typically below HRmax. If the computed LTHR is at or above 95% of the observed max, flag that the max is probably under-observed.
  - The talk test: easy runs at the top of Zone 2 should still allow full sentences.

### 4.5 HRmax and resting HR (only for the Max HR and HRR models)
- **HRmax:** the maximum of the cleaned 5 s-rolling-mean HR across the last 12 months of runs, races and tests. Do not use single-sample peaks, which are often artifacts. This is a lower bound. Age formulas give 184-190 bpm for age 33. If the observed max is far below that (for example the 172 bpm in the sample interval session), it is probably under-observed, not real.
- **Resting HR:** the median of the last 14 days from `queryRestingHeartRate`.

---

## 5. Mapping the result to COROS

### 5.1 Zone models COROS supports
Source: [COROS Heart Rate Zones: The Ultimate Guide](https://coros.com/stories/coros-metrics/c/coros-heart-rate-zones-the-ultimate-guide); COROS support "April 2023 Update Common Questions" and "Setting Resting and Max Heart Rate Data" (support.coros.com returned 403 to my fetch, so their content comes from search-engine snippets of those pages).

| Model | Anchors | Zones | Default boundaries |
|---|---|---|---|
| **Lactate Threshold (EvoLab default)** | Threshold HR | 6 | Z1 Recovery < 80%; Z2 Aerobic Endurance 80-90%; Z3 Aerobic Power 90-95%; Z4 Threshold 95-102%; Z5 Anaerobic Endurance 102-106%; Z6 Anaerobic Power > 106% of LTHR **(verified on coros.com)** |
| Heart Rate Reserve | Max HR + Resting HR | 6 | **Default percentages not verified.** coros.com shows them only as an image. Read them in the app after selecting the model |
| Max Heart Rate | Max HR | 6 | **Not verified**, same reason |

All three models allow editing the zone percentages (custom zones). EvoLab always uses its LT model internally for its metrics, whatever display model you choose (per the COROS guide).

### 5.2 Entering the value
- **Max HR and Resting HR:** editable in the COROS app under Profile > Settings > Heart Rate Zones (choose Max HR or HR Reserve). This comes from the COROS FAQ snippet.
- **Threshold HR (LTHR): conflicting COROS documentation.**
  - The April 2023 EvoLab FAQ says the LT value "can only be automatically adjusted by the algorithm" or via the watch's **Running Fitness Test**.
  - The COROS iOS app release notes (V3.1.6, 21 Aug 2023, per search snippet) list "the ability to modify your Lactate Threshold Heart Rate and Pace".
  - The Training Hub manual says you can "customize maximum heart rate, resting heart rate, lactate threshold heart rate, and percentage of different zones".
  - **Practical path:**
    1. Try the COROS app: Profile > Heart Rate Zone > Lactate Threshold > edit Threshold HR.
    2. If it is not editable on your app version, use **COROS Training Hub (training.coros.com) > Settings > Zones** and set LTHR there. Sync the watch afterwards.
    3. As a last resort, run the watch's Running Fitness Test and compare.
  - Verify on your device. I could not open the support pages directly.
- **Worked example** (hypothetical LTHR = 170 bpm), COROS LT model:

  | Zone | Range |
  |---|---|
  | Z1 | < 136 |
  | Z2 | 136-153 |
  | Z3 | 153-161.5 |
  | Z4 | 161.5-173.4 |
  | Z5 | 173.4-180.2 |
  | Z6 | > 180 |

  Rounded, enter Z1 ≤ 135, Z2 136-152, Z3 153-161, Z4 162-173, Z5 174-180, Z6 ≥ 181.
- **Side effect worth noting:** COROS structured workouts express intensity as % of threshold HR or pace (see `createSingleWorkout` in `COROS_CAPABILITIES.md`). A correct LTHR therefore also fixes the intensity of every workout this app pushes.

---

## 6. Ultra and marathon note
For marathon and ultra training, the zone that matters most is the top of easy (Z2 / LT1). LT1 is not measured by the 30-min test. COROS's Z2 ceiling at 90% of LTHR is a population convention. Nuuttila et al. (2025) show that LT1 as a fraction of max differs by sex and individual. Cross-check Z2 with the talk test and with HR-pace decoupling on long runs (under 5% over 90 min). If easy runs at 89% of LTHR cannot be held conversationally in Delhi heat, cap easy runs lower (85%), as in Friel's running Z2 (85-89%).

---

## 7. Data availability: is the sync sufficient?

**Verdict: yes.** Per-second HR is available through the FIT file, and arbitrary-window average HR is available directly through MCP. Per-lap HR alone is also enough for the basic Friel number if the test has a lap or step boundary at 10:00.

Evidence from the samples (activity `480672546503557126`, PACE 3, 8.40 km interval session):

- `queryActivityFitFileDownloadUrls.txt`:
  ```
  Activity FIT file download URL(s):
  1. 480672546503557126.fit
     https://s3.coros.com/fit/460648181682683919/480672546503557126.fit
  ```
- Decoded that FIT during this research (with `fitdecode`, in a scratch directory, not added to the project):
  - 3173 `record` messages
  - **3172 of 3172 inter-sample intervals = 1.0 s**
  - 2 records without `heart_rate` (the very first samples)
  - Sample record: `{'timestamp': 2026-09-29 00:32:24Z, 'distance': 1207.5, 'heart_rate': 147, 'enhanced_speed': 2.478, 'cadence': 87, 'power': 210, 'enhanced_altitude': 197.0, ...}`
  - `session`: `avg_heart_rate 155, max_heart_rate 172, min_heart_rate 104, avg_temperature 28`
  - No `hrv` (RR-interval) messages and no `zones_target`/`hr_zone` messages, so DFA-alpha1 is not possible and the watch's zone settings are not in the file.
- `queryActivityLapData.txt` gives per-lap HR in several lap groups. Type 11 is workout steps, type 10 is auto-km, type 2 is manual laps, and -1 is the whole activity:
  ```
  "lapGroups":[{"type":11,"lapDistance":500000,...,"laps":[{"lapIndex":1,"distance":0,"time":300.00,"totalLength":300.00,...,"avgHr":137,"maxHr":143,...},{"lapIndex":2,...,"time":900.00,"totalLength":1200.00,...,"avgHr":145,"maxHr":155,...
  ```
- `queryCustomActivityLapData.txt` gives HR for an arbitrary 600 s window:
  ```
  ARGS: {"labelId": "480672546503557126", "sportType": 100, "startTimestamp": 1790641745, "endTimestamp": 1790642345}
  ..."laps":[{"lapIndex":0,"distance":1462,"time":600,"totalLength":600,...,"avgHr":144,"maxHr":149,...}]
  ```
- `getActivityDetail.txt` gives the whole-activity average only (`Average Heart Rate: 155 bpm`). `analyzeActivityDetail.txt` gives average and peak only (`averaged 155 bpm, peaking at 172 bpm`). Neither is sufficient alone.
- `queryFitnessAssessmentOverview.txt`: `VO2max: 46 ... Threshold Pace: 5:12 /km`. **No threshold HR.** `COROS_CAPABILITIES.md` also notes that no MCP tool returns LTHR, HRmax or zones. The app cannot read the current COROS zones, so the user must type the current LTHR in for comparison.

---

## 8. Implementation outline

1. **"Zone test" session type.**
   - Add a plan session type `lthr_test` with the protocol text from section 3.
   - Optionally push it as a COROS structured workout via `createSingleWorkout`: 15:00 warm-up, a 10:00 "TT part 1" step, a 20:00 "TT part 2" step, and a 10:00 cool-down. Open or no target if the API allows. If it requires a target, use about 100% threshold pace with a wide range.
   - Schedule it at the start of each block, and suggest a retest after 6-8 weeks.
2. **Detection.** On sync, mark an activity as a zone test if any of these holds:
   - It matches the pushed workout's name or title (the `querySportRecords` "Location" field carries the title).
   - It has type-11 laps of about 600 s and about 1200 s.
   - The user taps "Use this run as a zone test".
3. **Computation service** (e.g. `app/analysis/hr_zones.py`):
   - Fetch the FIT URL, then download it (cached, counting against the 50/day quota), then parse 1 Hz records.
   - Find the window, clean it, and compute LTHR, drift, pace CV, missing %, cadence-lock % and confidence (section 4).
   - Fall back to `queryCustomActivityLapData` for the window when the FIT fails.
   - Store the result in a new `hr_zone_tests` table: date, labelId, LTHR, confidence, flags, temperature, sensor type, and the HRmax/RHR used.
4. **Zones display.**
   - Show the computed COROS LT-model zones. Optionally show Friel's 7-zone running model and the HRR/MaxHR equivalents when HRmax is observed.
   - Show a "± 8 bpm" band and a confidence badge, and a history chart of LTHR over time.
   - Compare with the previous test. Advise updating COROS only when the change is 3 bpm or more and confidence is Good or Fair.
5. **"How to enter in COROS" panel.**
   - Step-by-step instructions (section 5.2) with the six numbers ready to type.
   - A note that LTHR editing may need COROS Training Hub on some app versions.
   - A checkbox "I've updated COROS", which records the date so the coach logic knows which zones the watch is using.
6. **Coach integration.**
   - Use the stored LTHR to classify runs into zones from FIT time-in-zone.
   - Weight the result by test temperature: warn if the test ran above 28 °C and suggest a cool-weather retest.
   - Feed LTHR to the workout builder's % threshold targets.
7. **Tests.**
   - Unit tests for cleaning (pause, dropout, spike, cadence lock) using a synthetic 1 Hz series plus the sample FIT fixture.
   - Detection tests on lap structures.
   - A golden test: the Friel window average equals the `queryCustomActivityLapData` `avgHr` within 1 bpm on clean data.

### Implementation status (built 2026-10-09)

| Item | Status | Where |
|---|---|---|
| 1. Zone test session | Built. When no Good/Fair test exists in the last 56 days, the planner swaps the first eligible quality session in weeks 1-2 (build week only, > 10 days from the race, all guardrails still pass) for an `LTHR Test` session. The week's volume is kept by trimming that week's easy runs; only the 30-min core (60% of its km) counts as hard for the 80/20 rule. It can be sent to the watch with "Send to COROS" (10:00 + 20:00 steps give the lap split automatically). | `app/engine/planner.py`, `app/engine/guardrails.py` |
| 2. Detection | Partly built: the HR Zones page lists runs of 40+ min from the last 120 days, pre-selects one titled like a test, and you choose. No automatic analysis on sync (keeps the 50 FIT/day quota for runs you pick). | `app/analysis/zone_service.py` |
| 3. Computation | Built as specified in section 4 (window from 10:00 + 20:00 or 30:00 laps, else fastest 30 min; stops, dropouts, spikes, cadence lock; drift; confidence). FIT files are cached in `fit_cache/` beside the database (git-ignored). Lap-average fallback when the FIT can't be downloaded (never better than Fair). The `queryCustomActivityLapData` cross-check is not used. | `app/analysis/hr_zones.py` |
| 4. Zones display | Built for the COROS LT model only (HRR/Max HR defaults are unverified, so not shown). History table with change vs the previous usable test; no chart yet. | `/zones`, `app/templates/zones.html` |
| 5. "How to enter in COROS" | Built, with the "I've updated COROS" record. | `/zones` |
| 6. Coach integration | Partly built: plan heart-rate targets use COROS LT bands of the latest Good/Fair LTHR instead of max-HR estimates, and the plan's decisions cite the test. Time-in-zone classification of runs is not built. | `app/engine/planner.py` |
| 7. Tests | Built: `tests/test_hr_zones.py` (synthetic FIT files from `tests/fit_builder.py`, no personal data), `tests/e2e/test_e2e_zones.py`. | |

Open questions for the user:
- Does a chest strap exist?
- Can Threshold HR be edited in their COROS app version, or only in Training Hub?
- Do they prefer the LT model (recommended) or HRR?

---

## 9. Sources
- McGehee, Tanner, Houmard 2005: https://doi.org/10.1519/15444.1 (PubMed 16095403)
- Friel, TrainingPeaks zones guide: https://www.trainingpeaks.com/learn/articles/joe-friel-s-quick-guide-to-setting-zones/
- Tanaka, Monahan, Seals 2001: https://doi.org/10.1016/S0735-1097(00)01054-8 (PubMed 11153730)
- Gellish et al. 2007: https://doi.org/10.1097/mss.0b013e31803349c6 (PubMed 17468581)
- Nes et al. 2013: https://doi.org/10.1111/j.1600-0838.2012.01445.x
- Martin et al. 2025: https://doi.org/10.1371/journal.pone.0335842
- Nuuttila et al. 2025: https://doi.org/10.1007/s00421-025-05748-8
- Jones & Doust 1997: https://doi.org/10.1080/026404197367173
- Tanner, Millet, Bourdillon 2024: https://doi.org/10.1186/s40798-024-00768-8 (PMC11461412)
- Rogers et al. 2021: https://doi.org/10.3389/fphys.2020.596567; Rogers & Gronwald 2022: https://doi.org/10.3389/fphys.2022.879071
- Lu et al. 2025: https://doi.org/10.3389/fphys.2025.1621996 (PMC12309276)
- Reed & Pipe 2014: https://doi.org/10.1097/HCO.0000000000000097
- Gillinov et al. 2017: https://doi.org/10.1249/MSS.0000000000001284
- Wingo et al. 2005: https://doi.org/10.1249/01.MSS.0000152731.33450.95
- Faude, Kindermann, Meyer 2009: https://doi.org/10.2165/00007256-200939060-00003
- Jamnick et al. 2020: https://doi.org/10.1007/s40279-020-01322-8
- Seiler 2010 (intensity distribution background): https://doi.org/10.1123/ijspp.5.3.276
- COROS HR Zones guide: https://coros.com/stories/coros-metrics/c/coros-heart-rate-zones-the-ultimate-guide
- COROS What is Lactate Threshold: https://coros.com/us/stories/coros-coaches/c/what-is-lactate-threshold
- COROS support (403 to direct fetch; content via search snippets): https://support.coros.com/hc/en-us/articles/15705566771604-April-2023-Update-Common-Questions, https://support.coros.com/hc/en-us/articles/360040258391-Setting-Resting-and-Max-Heart-Rate-Data, https://support.coros.com/hc/en-us/articles/5146420791060-COROS-App-Release-Notes-iOS, https://support.coros.com/hc/en-us/articles/4412176269844-COROS-Training-Hub-Manual, https://support.coros.com/hc/en-us/articles/14990572238484-Fitness-Tests
