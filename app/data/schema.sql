-- Personal Running Coach SQLite Database Schema

CREATE TABLE IF NOT EXISTS activities (
    id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    sport_type TEXT NOT NULL DEFAULT 'Run',
    name TEXT,
    distance_m REAL NOT NULL,
    duration_s REAL NOT NULL,
    avg_pace_s_km REAL,
    elevation_gain_m REAL,
    elevation_loss_m REAL,
    gap_s_km REAL,
    avg_hr INTEGER,
    max_hr INTEGER,
    avg_cadence INTEGER,
    stride_length_cm REAL,
    ground_contact_time_ms REAL,
    vertical_oscillation_mm REAL,
    avg_power_w REAL,
    calories REAL,
    raw_payload TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS activity_splits (
    id TEXT PRIMARY KEY,
    activity_id TEXT NOT NULL,
    split_index INTEGER NOT NULL,
    distance_m REAL NOT NULL,
    duration_s REAL NOT NULL,
    avg_pace_s_km REAL,
    avg_hr INTEGER,
    avg_cadence INTEGER,
    elevation_gain_m REAL,
    FOREIGN KEY(activity_id) REFERENCES activities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sleep_records (
    id TEXT PRIMARY KEY,
    date TEXT NOT NULL UNIQUE,
    total_sleep_minutes INTEGER NOT NULL,
    sleep_score INTEGER,
    deep_sleep_minutes INTEGER,
    light_sleep_minutes INTEGER,
    rem_sleep_minutes INTEGER,
    awake_minutes INTEGER,
    raw_payload TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS daily_physiology (
    id TEXT PRIMARY KEY,
    date TEXT NOT NULL UNIQUE,
    resting_hr INTEGER,
    avg_hr INTEGER,
    hrv_score REAL,
    rmssd_ms REAL,
    vo2max REAL,
    acute_load REAL,
    chronic_load REAL,
    fatigue_index REAL,
    recovery_score REAL,
    weight_kg REAL,
    raw_payload TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sync_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sync_type TEXT NOT NULL,
    status TEXT NOT NULL,
    records_fetched INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    duration_ms INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    race_distance_type TEXT NOT NULL DEFAULT 'Marathon',
    race_date TEXT,
    target_time_str TEXT,
    weekly_hours_available REAL DEFAULT 8.0,
    available_days TEXT DEFAULT 'Mon,Tue,Thu,Sat,Sun',
    injury_history TEXT,
    current_niggles TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS training_plans (
    id TEXT PRIMARY KEY,
    version INTEGER DEFAULT 1,
    goal_distance TEXT NOT NULL,
    race_date TEXT,
    total_volume_km REAL NOT NULL,
    methodology_name TEXT NOT NULL,
    methodology_rationale TEXT NOT NULL,
    is_deload INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    start_date TEXT,
    end_date TEXT,
    total_weeks INTEGER
);

CREATE TABLE IF NOT EXISTS plan_sessions (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    day_of_week TEXT NOT NULL,
    session_type TEXT NOT NULL,
    distance_km REAL,
    duration_min REAL,
    target_pace_or_hr TEXT,
    stated_purpose TEXT NOT NULL,
    matched_activity_id TEXT,
    status TEXT NOT NULL DEFAULT 'Pending',
    user_notes TEXT,
    actual_distance_km REAL,
    actual_duration_min REAL,
    actual_avg_pace_s_km REAL,
    actual_avg_hr INTEGER,
    post_run_feedback TEXT,
    session_date TEXT,
    week_number INTEGER,
    FOREIGN KEY(plan_id) REFERENCES training_plans(id) ON DELETE CASCADE,
    FOREIGN KEY(matched_activity_id) REFERENCES activities(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS block_summaries (
    id TEXT PRIMARY KEY,
    block_number INTEGER NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    total_prescribed_km REAL NOT NULL,
    total_completed_km REAL NOT NULL,
    compliance_pct REAL NOT NULL,
    key_achievements TEXT,
    areas_for_improvement TEXT,
    fatigue_signals_summary TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS strength_exercises (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    movement_pattern TEXT NOT NULL,
    equipment_needed TEXT NOT NULL,
    contraindicated_niggles TEXT,
    default_sets INTEGER DEFAULT 3,
    default_reps TEXT DEFAULT '10',
    default_rpe INTEGER DEFAULT 7,
    safety_cues TEXT
);

CREATE TABLE IF NOT EXISTS strength_workouts (
    id TEXT PRIMARY KEY,
    phase TEXT NOT NULL,
    focus_area TEXT NOT NULL,
    total_duration_min INTEGER DEFAULT 40,
    workout_data_json TEXT NOT NULL,
    status TEXT DEFAULT 'Prescribed',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);


