"""Data models and data structure definitions for running activities, sleep, and physiology."""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

@dataclass
class ActivitySplit:
    id: str
    activity_id: str
    split_index: int
    distance_m: float
    duration_s: float
    avg_pace_s_km: Optional[float] = None
    avg_hr: Optional[int] = None
    avg_cadence: Optional[int] = None
    elevation_gain_m: Optional[float] = None

@dataclass
class Activity:
    id: str
    date: str
    distance_m: float
    duration_s: float
    sport_type: str = "Run"
    name: Optional[str] = None
    avg_pace_s_km: Optional[float] = None
    elevation_gain_m: Optional[float] = None
    elevation_loss_m: Optional[float] = None
    gap_s_km: Optional[float] = None
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    avg_cadence: Optional[int] = None
    stride_length_cm: Optional[float] = None
    ground_contact_time_ms: Optional[float] = None
    vertical_oscillation_mm: Optional[float] = None
    avg_power_w: Optional[float] = None
    calories: Optional[float] = None
    raw_payload: Optional[str] = None
    splits: List[ActivitySplit] = field(default_factory=list)

@dataclass
class SleepRecord:
    id: str
    date: str
    total_sleep_minutes: int
    sleep_score: Optional[int] = None
    deep_sleep_minutes: Optional[int] = None
    light_sleep_minutes: Optional[int] = None
    rem_sleep_minutes: Optional[int] = None
    awake_minutes: Optional[int] = None
    raw_payload: Optional[str] = None

@dataclass
class DailyPhysiology:
    id: str
    date: str
    resting_hr: Optional[int] = None
    avg_hr: Optional[int] = None
    hrv_score: Optional[float] = None
    rmssd_ms: Optional[float] = None
    vo2max: Optional[float] = None
    acute_load: Optional[float] = None
    chronic_load: Optional[float] = None
    fatigue_index: Optional[float] = None
    recovery_score: Optional[float] = None
    weight_kg: Optional[float] = None
    raw_payload: Optional[str] = None

@dataclass
class SyncLog:
    id: Optional[int]
    timestamp: str
    sync_type: str
    status: str
    records_fetched: int
    error_message: Optional[str] = None
    duration_ms: int = 0
