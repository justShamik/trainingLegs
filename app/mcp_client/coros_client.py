"""COROS MCP Client.

Provides authentication and communication interface with the official COROS MCP gateway (coros-mcp).
Supports browser-based OAuth login triggering and tool data extraction.
"""
import os
import re
import json
import subprocess
import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple

DEFAULT_COROS_MCP_URL = os.getenv("COROS_MCP_SERVER_URL", "https://mcp.coros.com/mcp")
CACHE_TOKEN_PATH = os.path.expanduser(r"~\.coros-mcp-skill-gateway-ts\us\token.json")

def find_npx_executable() -> str:
    """Locate npx executable path on system."""
    node_path = r"C:\Program Files\nodejs"
    npx_cmd = os.path.join(node_path, "npx.cmd")
    if os.path.exists(npx_cmd):
        return npx_cmd
    return "npx"

class CorosMCPClient:
    """Client for interacting with the COROS MCP gateway CLI (coros-mcp)."""

    def __init__(self, server_url: Optional[str] = None, token: Optional[str] = None) -> None:
        self.server_url = server_url or DEFAULT_COROS_MCP_URL
        self.token = token or os.getenv("COROS_MCP_AUTH_TOKEN")
        self.npx_bin = find_npx_executable()
        self.call_failures: List[str] = []

    def is_authenticated(self) -> bool:
        """Check if local COROS token cache exists."""
        if os.path.exists(CACHE_TOKEN_PATH):
            return True
        if self.token:
            return True
        return False

    def validate_token_status(self) -> Dict[str, Any]:
        """Validate if COROS token exists and whether it is valid."""
        token_exists = os.path.exists(CACHE_TOKEN_PATH) or bool(self.token)
        if not token_exists:
            return {
                "is_authenticated": False,
                "token_exists": False,
                "status_code": "NOT_CONNECTED",
                "message": "COROS token missing. Browser authentication required."
            }

        expires_iso = None
        if os.path.exists(CACHE_TOKEN_PATH) and not self.token:
            try:
                with open(CACHE_TOKEN_PATH, "r", encoding="utf-8") as f:
                    token_data = json.load(f)
                expires_at = token_data.get("expires_at")
                if not token_data.get("access_token"):
                    raise ValueError("no access_token")
                if expires_at is not None:
                    exp = float(expires_at)
                    if exp > 1e11:  # milliseconds
                        exp /= 1000.0
                    expires_iso = datetime.fromtimestamp(exp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    if exp < datetime.now(timezone.utc).timestamp():
                        raise ValueError("expired")
            except Exception:
                return {
                    "is_authenticated": False,
                    "token_exists": True,
                    "status_code": "TOKEN_EXPIRED",
                    "message": "COROS Token expired or invalid. Please re-authenticate.",
                    "expires_at": expires_iso,
                }

        if os.path.exists(CACHE_TOKEN_PATH) or self.token:
            return {
                "is_authenticated": True,
                "token_exists": True,
                "status_code": "CONNECTED",
                "message": "COROS Account Authenticated & Token Valid",
                "expires_at": expires_iso,
            }

        return {
            "is_authenticated": False,
            "token_exists": True,
            "status_code": "TOKEN_EXPIRED",
            "message": "COROS Token expired or invalid. Please re-authenticate."
        }

    def trigger_login_flow(self) -> bool:
        """Launch coros-mcp login non-blocking to open browser login window."""
        try:
            env = dict(os.environ)
            node_path = r"C:\Program Files\nodejs"
            if node_path not in env.get("PATH", ""):
                env["PATH"] = f"{node_path};{env.get('PATH', '')}"

            cmd = [self.npx_bin, "-y", "coros-mcp", "login"]
            subprocess.Popen(cmd, env=env, creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0)
            return True
        except Exception:
            return False

    def _call_cli_tool(self, tool_name: str, arguments: dict) -> Optional[str]:
        """Invoke an MCP tool via coros-mcp call-tool CLI."""
        env = dict(os.environ)
        node_path = r"C:\Program Files\nodejs"
        if node_path not in env.get("PATH", ""):
            env["PATH"] = f"{node_path};{env.get('PATH', '')}"

        args_json = json.dumps(arguments)
        cmd = [self.npx_bin, "-y", "coros-mcp", "call-tool", "--tool", tool_name, "--arguments-json", args_json]
        
        try:
            res = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
            if res.returncode == 0:
                out = json.loads(res.stdout)
                content = out.get("content", [])
                if content and isinstance(content, list) and len(content) > 0:
                    text_val = content[0].get("text", "")
                    # Some COROS tools return the text as a JSON-encoded string ("...\\n...");
                    # unwrap it so line breaks are real newlines the parsers can split on.
                    if isinstance(text_val, str) and text_val.startswith('"') and text_val.endswith('"'):
                        try:
                            text_val = json.loads(text_val)
                        except ValueError:
                            pass
                    return text_val
                return None
            self.call_failures.append(f"{tool_name}: {(res.stderr or '').strip()[:120] or 'exit code ' + str(res.returncode)}")
            return None
        except Exception as err:
            self.call_failures.append(f"{tool_name}: {type(err).__name__}")
        return None

    def fetch_workouts(self, since_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch workout summaries from COROS MCP querySportRecords tool."""
        start_dt = datetime.now(timezone.utc) - timedelta(days=365)
        if since_date and len(since_date) >= 10:
            try:
                # One day of overlap covers timezone differences; saves are idempotent upserts
                start_dt = datetime.strptime(since_date[:10], "%Y-%m-%d") - timedelta(days=1)
            except ValueError:
                pass
        start_date = start_dt.strftime("%Y%m%d")

        # COROS local dates can be a day ahead of UTC
        end_date = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y%m%d")

        cli_text = self._call_cli_tool("querySportRecords", {
            "startDate": start_date,
            "endDate": end_date,
            "limit": 300
        })

        if cli_text:
            return self._parse_sport_records(cli_text)

        # Fallback to direct HTTP endpoint if token set
        if self.token:
            payload = {"method": "query_workouts", "params": {}}
            if since_date:
                payload["params"]["since"] = since_date
            try:
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"}
                res = requests.post(self.server_url, json=payload, headers=headers, timeout=5)
                if res.status_code == 200:
                    return res.json().get("workouts", [])
            except Exception:
                pass
        return []

    def fetch_daily_physiology(self, since_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch daily physiology, training load, VO2max & recovery from COROS MCP tools."""
        days = 30
        if since_date:
            try:
                s_dt = datetime.strptime(since_date[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                days = min(90, max(1, (datetime.now(timezone.utc) - s_dt).days + 1))
            except Exception:
                days = 30

        load_text = self._call_cli_tool("queryTrainingLoadAssessment", {"days": days})
        fitness_text = self._call_cli_tool("queryFitnessAssessmentOverview", {})
        recovery_text = self._call_cli_tool("queryRecoveryStatus", {})

        records = self._parse_training_load(load_text or "")
        fitness_data = self._parse_fitness_overview(fitness_text or "")
        recovery_data = self._parse_recovery_status(recovery_text or "")

        # HRV (max 7 days per call) and resting HR, merged into the matching day
        by_date = {r["date"]: r for r in records}
        hrv_text = self._call_cli_tool("querySleepHrv", {
            "startDate": (datetime.now(timezone.utc) - timedelta(days=6)).strftime("%Y%m%d"),
            "endDate": (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y%m%d"),
            "days": 7
        })
        rhr_text = self._call_cli_tool("queryRestingHeartRate", {"days": min(90, max(days, 7))})
        for date_str, hrv in self._parse_hrv(hrv_text or "").items():
            by_date.setdefault(date_str, {"id": f"physio_{date_str}", "date": date_str}).update(hrv)
        for date_str, rhr in self._parse_resting_hr(rhr_text or "").items():
            by_date.setdefault(date_str, {"id": f"physio_{date_str}", "date": date_str})["resting_hr"] = rhr
        records = sorted(by_date.values(), key=lambda r: r["date"])

        # Fitness and recovery are point-in-time snapshots: attach only to the newest day
        if records:
            latest = max(records, key=lambda r: r["date"])
            if "vo2max" in fitness_data:
                latest["vo2max"] = fitness_data["vo2max"]
            if "recovery_score" in recovery_data:
                latest["recovery_score"] = recovery_data["recovery_score"]

        return records

    def fetch_daily_health(self, since_date: Optional[str] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """One queryDailyHealthData call -> (sleep nights, daily activity totals).

        querySleepData is rejected by the gateway; this tool takes only `days` (up to 365, always
        ending today), so one call suffices. COROS provides no sleep score; it stays NULL."""
        days = 30
        if since_date:
            try:
                s_dt = datetime.strptime(since_date[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                days = min(365, max(7, (datetime.now(timezone.utc) - s_dt).days + 2))
            except Exception:
                days = 30
        text = self._call_cli_tool("queryDailyHealthData", {"days": days})
        if not text:
            return [], []
        return self._parse_daily_health_sleep(text), self._parse_daily_activity(text)

    def fetch_sleep_records(self, since_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Sleep nights only (see fetch_daily_health)."""
        return self.fetch_daily_health(since_date)[0]

    @staticmethod
    def _split_health_days(text: str):
        """Yield (iso_date, block) for each '--- yyyymmdd ---' day of queryDailyHealthData."""
        for block in re.split(r'\n(?=--- \d{8} ---)', text.replace("\r\n", "\n")):
            d = re.match(r'--- (\d{4})(\d{2})(\d{2}) ---', block.strip())
            if d:
                yield f"{d.group(1)}-{d.group(2)}-{d.group(3)}", block.strip()

    def _parse_daily_activity(self, text: str) -> List[Dict[str, Any]]:
        """Parse Steps / Calories / Exercise / Stress per day. Absent values stay None (NFR-4.1);
        days with none of them are skipped."""
        def num(pattern, block):
            m = re.search(pattern, block)
            return float(m.group(1).replace(",", "")) if m else None
        records = []
        for date_str, block in self._split_health_days(text):
            head = block.split("Sleep Summary:", 1)[0]
            steps = num(r'Steps:\s*([\d,]+)', head)
            ex = re.search(r'Exercise:\s*([^|\n]+)', head)
            exercise = self._dur_to_min(ex.group(1)) if ex else None
            rec = {
                "date": date_str,
                "steps": int(steps) if steps is not None else None,
                "calories_kcal": num(r'Calories:\s*([\d,\.]+)\s*kcal', head),
                "exercise_minutes": float(exercise) if exercise is not None else None,
                "stress_avg": num(r'Stress:\s*Avg\s*([\d\.]+)', head),
            }
            if all(rec[k] is None for k in ("steps", "calories_kcal", "exercise_minutes", "stress_avg")):
                continue
            rec["raw_payload"] = head.strip()
            records.append(rec)
        return records

    @staticmethod
    def _dur_to_min(s: Optional[str]) -> Optional[int]:
        """'8h 3min' / '46 min' / '2h' -> minutes."""
        if not s:
            return None
        h = re.search(r'(\d+)\s*h', s)
        m = re.search(r'(\d+)\s*min', s)
        if not h and not m:
            return None
        return (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0)

    def _parse_daily_health_sleep(self, text: str) -> List[Dict[str, Any]]:
        """Parse the 'Sleep Summary' of each '--- yyyymmdd ---' day of queryDailyHealthData.

        Total is COROS's time-in-bed style total (it includes Awake). Stage minutes are stored
        as NULL when COROS reports no stage split (nap/partial nights show all-zero stages).
        Days without a Sleep Summary are skipped (never fabricated, NFR-4.1)."""
        records = []
        for date_str, block in self._split_health_days(text):
            if "Sleep Summary" not in block:
                continue
            sleep = block.split("Sleep Summary:", 1)[1]
            total = re.search(r'Total:\s*([^|\n]+)', sleep)
            total_min = self._dur_to_min(total.group(1)) if total else None
            if not total_min:
                continue
            def stage(name):
                m = re.search(name + r':\s*([^|\n]+)', sleep)
                return self._dur_to_min(m.group(1)) if m else None
            deep, light, rem, awake = stage("Deep"), stage("Light"), stage("REM"), stage("Awake")
            if not (deep or light or rem):
                deep = light = rem = awake = None  # no stage split reported
            hr = re.search(r'Sleep HR:\s*Avg\s*(\d+)\s*bpm(?:\s*\|\s*Min\s*(\d+)(?:\s*bpm)?)?(?:\s*\|\s*Max\s*(\d+))?', sleep)
            rec = {
                "id": f"sleep_{date_str}",
                "date": date_str,
                "total_sleep_minutes": total_min,
                "sleep_score": None,
                "deep_sleep_minutes": deep,
                "light_sleep_minutes": light,
                "rem_sleep_minutes": rem,
                "awake_minutes": awake,
            }
            if hr:
                rec["sleep_hr_avg"] = int(hr.group(1))
                if hr.group(2):
                    rec["sleep_hr_min"] = int(hr.group(2))
                if hr.group(3):
                    rec["sleep_hr_max"] = int(hr.group(3))
            records.append(rec)
        return records

    # Activity detail enrichment (running form metrics are NOT in the querySportRecords summary)
    @staticmethod
    def running_sport_code(sport_name: Optional[str]) -> Optional[int]:
        """Map a COROS sport name to its run sportType code (100-103); None for non-running sports."""
        n = (sport_name or "").lower()
        if "run" not in n:
            return None
        if "trail" in n:
            return 102
        if "track" in n:
            return 103
        if "indoor" in n or "treadmill" in n:
            return 101
        return 100

    def fetch_activity_details(self, label_id: str, sport_code: int = 100) -> Optional[Dict[str, Any]]:
        """Fetch per-activity metrics + splits. Lap data is the primary source; the text
        getActivityDetail output is a fallback. Returns None when neither call gave data."""
        args = {"labelId": str(label_id), "sportType": sport_code}
        lap_text = self._call_cli_tool("queryActivityLapData", args)
        parsed = self._parse_lap_data(lap_text) if lap_text else None
        if parsed:
            return parsed
        detail_text = self._call_cli_tool("getActivityDetail", args)
        if detail_text:
            return self._parse_activity_detail_text(detail_text) or None
        return None

    def fetch_lap_list(self, label_id: str, sport_code: int = 100) -> List[Dict[str, Any]]:
        """Workout-step laps (type 11), else manual laps (type 2), in order. [] when unavailable."""
        text = self._call_cli_tool("queryActivityLapData", {"labelId": str(label_id), "sportType": sport_code})
        try:
            groups = json.loads(text or "").get("lapGroups") or []
        except (ValueError, AttributeError):
            return []
        by_type = {g.get("type"): g.get("laps") or [] for g in groups}
        return by_type.get(11) or by_type.get(2) or []

    FIT_MAX_BYTES = 20 * 1024 * 1024

    def fetch_fit_bytes(self, label_id: str, sport_code: int = 100) -> Optional[bytes]:
        """Download the activity's FIT file (per-second records). Only https URLs on coros.com are fetched.
        COROS allows 50 FIT downloads per 24 h, so callers should cache the result."""
        import requests
        from urllib.parse import urlsplit

        text = self._call_cli_tool("queryActivityFitFileDownloadUrls",
                                   {"labelId": str(label_id), "sportType": sport_code, "limit": 1})
        for url in re.findall(r"https://\S+?\.fit\b", text or ""):
            host = (urlsplit(url).hostname or "").lower()
            if not (host == "coros.com" or host.endswith(".coros.com")):
                self.call_failures.append(f"fit download: untrusted host {host}")
                continue
            try:
                with requests.get(url, timeout=30, stream=True) as resp:
                    resp.raise_for_status()
                    data = bytearray()
                    for chunk in resp.iter_content(65536):
                        data.extend(chunk)
                        if len(data) > self.FIT_MAX_BYTES:
                            raise ValueError("FIT file too large")
                    return bytes(data)
            except Exception as err:
                self.call_failures.append(f"fit download: {type(err).__name__}")
        return None

    @staticmethod
    def _pace_to_s(text: str) -> Optional[int]:
        m = re.match(r'\s*(\d+):(\d{2})', text or "")
        return int(m.group(1)) * 60 + int(m.group(2)) if m else None

    def _parse_activity_detail_text(self, text: str) -> Dict[str, Any]:
        """Parse getActivityDetail text ('Average Cadence: 176 spm', ...). Only present fields are returned."""
        out: Dict[str, Any] = {}
        def grab(pattern):
            m = re.search(pattern, text)
            return m.group(1) if m else None
        v = grab(r'Average Cadence:\s*(\d+)\s*spm')
        if v:
            out["avg_cadence"] = int(v)
        v = grab(r'Average Stride Length:\s*([\d\.]+)\s*m')
        if v:
            out["stride_length_cm"] = round(float(v) * 100, 1)
        v = grab(r'Average Power:\s*(\d+)\s*W')
        if v:
            out["avg_power_w"] = float(v)
        v = grab(r'Adjusted Pace:\s*(\d+:\d{2})')
        if v:
            out["gap_s_km"] = self._pace_to_s(v)
        m = re.search(r'Elevation Gain / Loss:\s*(\d+)\s*m\s*/\s*(\d+)\s*m', text)
        if m:
            out["elevation_gain_m"] = float(m.group(1))
            out["elevation_loss_m"] = float(m.group(2))
        v = grab(r'Average Heart Rate:\s*(\d+)\s*bpm')
        if v:
            out["avg_hr"] = int(v)
        return out

    def _parse_lap_data(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse queryActivityLapData JSON. Distances are in cm, stride in cm, oscillation in mm.
        A value of 0 means the watch did not record that metric -> left out (NULL), never faked."""
        try:
            data = json.loads(text)
            groups = data.get("lapGroups") or []
        except (ValueError, AttributeError):
            return None
        by_type = {g.get("type"): g.get("laps") or [] for g in groups}
        overall = (by_type.get(-1) or [None])[0]
        if not overall:
            return None

        def pos(v):
            return v if isinstance(v, (int, float)) and v > 0 else None

        out: Dict[str, Any] = {}
        for key, field, conv in (
            ("avgCadence", "avg_cadence", int), ("avgStrideLength", "stride_length_cm", float),
            ("avgPower", "avg_power_w", float), ("adjustedPace", "gap_s_km", float),
            ("maxHr", "max_hr", int), ("avgHr", "avg_hr", int),
        ):
            if pos(overall.get(key)) is not None:
                out[field] = conv(overall[key])
        if "elevGain" in overall:
            out["elevation_gain_m"] = float(overall["elevGain"])
        if "totalDescent" in overall:
            out["elevation_loss_m"] = float(overall["totalDescent"])

        # Split table: per-km laps (type 10), else workout-step laps (11), else auto laps (2)
        split_laps = by_type.get(10) or by_type.get(11) or by_type.get(2) or []

        # Ground contact / vertical oscillation are only reported per lap: time-weighted mean
        for key, field in (("groundTime", "ground_contact_time_ms"), ("strideHeight", "vertical_oscillation_mm")):
            num = den = 0.0
            for lap in split_laps:
                val, t = pos(lap.get(key)), pos(lap.get("time"))
                if val is not None and t is not None:
                    num += val * t
                    den += t
            if den > 0:
                out[field] = round(num / den, 1)

        splits = []
        for lap in split_laps:
            dist_m = (lap.get("distance") or 0) / 100.0
            dur = lap.get("time") or 0
            if dist_m <= 0 or dur <= 0:
                continue
            idx = int(lap.get("lapIndex") or len(splits) + 1)
            splits.append({
                "split_index": idx,
                "distance_m": round(dist_m, 1),
                "duration_s": round(float(dur), 1),
                "avg_pace_s_km": pos(lap.get("avgPace")) or round(dur / (dist_m / 1000.0), 1),
                "avg_hr": int(lap["avgHr"]) if pos(lap.get("avgHr")) else None,
                "avg_cadence": int(lap["avgCadence"]) if pos(lap.get("avgCadence")) else None,
                "elevation_gain_m": float(lap["elevGain"]) if lap.get("elevGain") is not None else None,
            })
        if splits:
            out["splits"] = splits
        return out

    # Parsers
    def _parse_sport_records(self, text: str) -> List[Dict[str, Any]]:
        records = []
        blocks = re.split(r'\n(?=\d+\.\s+)', text)
        for block in blocks:
            if not block.strip():
                continue
            
            header_match = re.search(r'\d+\.\s+([^\n—]+)\s*—\s*(\d{4}-\d{2}-\d{2})', block)
            if not header_match:
                continue
                
            sport_name = header_match.group(1).strip()
            date_str = header_match.group(2).strip()

            label_id_match = re.search(r'LabelId:\s*(\d+)', block)
            label_id = label_id_match.group(1) if label_id_match else None

            location_match = re.search(r'Location:\s*([^\n]+)', block)
            location = location_match.group(1).strip() if location_match else sport_name

            dur_match = re.search(r'Duration:\s*([\d:]+)', block)
            duration_s = 0.0
            if dur_match:
                parts = [int(p) for p in dur_match.group(1).split(':')]
                if len(parts) == 3:
                    duration_s = parts[0] * 3600 + parts[1] * 60 + parts[2]
                elif len(parts) == 2:
                    duration_s = parts[0] * 60 + parts[1]

            dist_match = re.search(r'Distance:\s*([\d\.]+)\s*(km|m)', block)
            distance_m = 0.0
            if dist_match:
                val = float(dist_match.group(1))
                unit = dist_match.group(2)
                distance_m = val * 1000.0 if unit == 'km' else val

            pace_match = re.search(r'Average Pace:\s*(\d+):(\d+)', block)
            avg_pace_s_km = None
            if pace_match:
                mins = int(pace_match.group(1))
                secs = int(pace_match.group(2))
                avg_pace_s_km = mins * 60 + secs

            hr_match = re.search(r'Avg HR:\s*(\d+)\s*bpm', block)
            avg_hr = int(hr_match.group(1)) if hr_match else None

            cal_match = re.search(r'Calories:\s*([\d\.]+)\s*kcal', block)
            calories = float(cal_match.group(1)) if cal_match else None

            records.append({
                "id": label_id or f"act_{date_str}_{sport_name.replace(' ', '_')}",
                "date": f"{date_str}T08:00:00Z",
                "sport_type": sport_name,
                "name": location,
                "distance_m": distance_m,
                "duration_s": duration_s,
                "avg_pace_s_km": avg_pace_s_km,
                "avg_hr": avg_hr,
                "calories": calories,
                "raw_payload": block.strip()
            })
        return records

    def _parse_fitness_overview(self, text: str) -> Dict[str, Any]:
        data = {}
        v_match = re.search(r'VO2max:\s*([\d\.]+)', text)
        if v_match:
            data["vo2max"] = float(v_match.group(1))
        t_match = re.search(r'Threshold Pace:\s*(\d+):(\d+)', text)
        if t_match:
            data["threshold_pace_s_km"] = int(t_match.group(1)) * 60 + int(t_match.group(2))
        r_match = re.search(r'Running Level:\s*([\d\.]+)', text)
        if r_match:
            data["running_level"] = float(r_match.group(1))
        return data

    def _parse_training_load(self, text: str) -> List[Dict[str, Any]]:
        records = []
        blocks = re.split(r'\n(?=\d{4}-\d{2}-\d{2})', text)
        for block in blocks:
            d_match = re.search(r'(\d{4}-\d{2}-\d{2})', block)
            if not d_match:
                continue
            date_str = d_match.group(1)
            st_match = re.search(r'Short-Term Load:\s*([\d\.]+)', block)
            lt_match = re.search(r'Long-Term Load:\s*([\d\.]+)', block)
            lr_match = re.search(r'Load Ratio:\s*([\d\.]+)', block)

            acute = float(st_match.group(1)) if st_match else None
            chronic = float(lt_match.group(1)) if lt_match else None
            ratio = float(lr_match.group(1)) if lr_match else None

            records.append({
                "id": f"physio_{date_str}",
                "date": date_str,
                "acute_load": acute,
                "chronic_load": chronic,
                "fatigue_index": ratio
            })
        return records

    def _parse_hrv(self, text: str) -> Dict[str, Dict[str, Any]]:
        """Parse 'HRV Assessment' blocks: date -> {hrv_score, rmssd_ms}."""
        result: Dict[str, Dict[str, Any]] = {}
        assessment = text.split("Sleep HRV Time Series")[0]
        for m in re.finditer(r'(\d{4}-\d{2}-\d{2}):\s*\n\s*HRV Avg:\s*(\d+)\s*ms', assessment):
            result[m.group(1)] = {"hrv_score": float(m.group(2)), "rmssd_ms": float(m.group(2))}
        return result

    def _parse_resting_hr(self, text: str) -> Dict[str, int]:
        return {m.group(1): int(m.group(2)) for m in re.finditer(r'(\d{4}-\d{2}-\d{2}):\s*(\d+)\s*bpm', text)}

    def _parse_recovery_status(self, text: str) -> Dict[str, Any]:
        data = {}
        r_match = re.search(r'Recovery:\s*(\d+)%', text)
        if r_match:
            data["recovery_score"] = int(r_match.group(1))
        return data

    def _parse_sleep_data(self, text: str) -> List[Dict[str, Any]]:
        records = []
        blocks = re.split(r'\n(?=\d{4}-\d{2}-\d{2})', text)
        for block in blocks:
            d_match = re.search(r'(\d{4}-\d{2}-\d{2})', block)
            if not d_match:
                continue
            date_str = d_match.group(1)
            score_match = re.search(r'Sleep Score:\s*(\d+)', block)
            dur_match = re.search(r'Duration:\s*([\d:]+)', block)
            
            total_min = None
            if dur_match:
                parts = [int(p) for p in dur_match.group(1).split(':')]
                if len(parts) in (2, 3):
                    total_min = parts[0] * 60 + parts[1]

            # Never fabricate sleep figures (NFR-4.1): skip nights with no data at all
            if total_min is None and not score_match:
                continue

            records.append({
                "id": f"sleep_{date_str}",
                "date": date_str,
                "total_sleep_minutes": total_min if total_min is not None else 0,
                "sleep_score": int(score_match.group(1)) if score_match else None,
                "raw_payload": block.strip()
            })
        return records
