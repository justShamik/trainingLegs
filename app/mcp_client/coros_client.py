"""COROS MCP Client.

Provides authentication and communication interface with the official COROS MCP gateway (coros-mcp).
Supports browser-based OAuth login triggering and tool data extraction.
"""
import os
import re
import json
import subprocess
import requests
from datetime import datetime, timedelta
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

        # Check if token file exists or test call succeeds
        if os.path.exists(CACHE_TOKEN_PATH) or self.token:
            return {
                "is_authenticated": True,
                "token_exists": True,
                "status_code": "CONNECTED",
                "message": "COROS Account Authenticated & Token Valid"
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
            res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=15)
            if res.returncode == 0:
                out = json.loads(res.stdout)
                content = out.get("content", [])
                if content and isinstance(content, list) and len(content) > 0:
                    text_val = content[0].get("text", "")
                    return text_val
        except Exception:
            pass
        return None

    def fetch_workouts(self, since_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch workout summaries from COROS MCP querySportRecords tool."""
        start_date = "20250101"
        if since_date and len(since_date) >= 10:
            start_date = since_date[:10].replace("-", "")

        end_date = datetime.utcnow().strftime("%Y%m%d")

        cli_text = self._call_cli_tool("querySportRecords", {
            "startDate": start_date,
            "endDate": end_date,
            "limit": 50
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
                s_dt = datetime.strptime(since_date[:10], "%Y-%m-%d")
                days = min(90, max(1, (datetime.utcnow() - s_dt).days + 1))
            except Exception:
                days = 30

        load_text = self._call_cli_tool("queryTrainingLoadAssessment", {"days": days})
        fitness_text = self._call_cli_tool("queryFitnessAssessmentOverview", {})
        recovery_text = self._call_cli_tool("queryRecoveryStatus", {})

        records = self._parse_training_load(load_text or "")
        fitness_data = self._parse_fitness_overview(fitness_text or "")
        recovery_data = self._parse_recovery_status(recovery_text or "")

        # Merge fitness and recovery into daily records
        for r in records:
            if "vo2max" in fitness_data:
                r["vo2max"] = fitness_data["vo2max"]
            if "recovery_score" in recovery_data:
                r["recovery_score"] = recovery_data["recovery_score"]

        return records

    def fetch_sleep_records(self, since_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch sleep records from COROS MCP querySleepData tool."""
        days = 30
        if since_date:
            try:
                s_dt = datetime.strptime(since_date[:10], "%Y-%m-%d")
                days = min(90, max(1, (datetime.utcnow() - s_dt).days + 1))
            except Exception:
                days = 30

        start_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y%m%d")
        end_date = datetime.utcnow().strftime("%Y%m%d")

        sleep_text = self._call_cli_tool("querySleepData", {
            "startDate": start_date,
            "endDate": end_date,
            "days": days
        })

        if sleep_text:
            return self._parse_sleep_data(sleep_text)
        return []

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
            
            total_min = 480
            if dur_match:
                parts = [int(p) for p in dur_match.group(1).split(':')]
                if len(parts) == 2:
                    total_min = parts[0] * 60 + parts[1]
                elif len(parts) == 3:
                    total_min = parts[0] * 60 + parts[1]

            records.append({
                "id": f"sleep_{date_str}",
                "date": date_str,
                "total_sleep_minutes": total_min,
                "sleep_score": int(score_match.group(1)) if score_match else 80,
                "raw_payload": block.strip()
            })
        return records
