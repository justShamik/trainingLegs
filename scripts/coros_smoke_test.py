"""Smoke-test every readOnlyHint=true COROS MCP tool (never calls write tools).

Run: .venv/Scripts/python scripts/coros_smoke_test.py
Needs Node on PATH (npx). Outputs: scripts/smoke_output/<tool>.txt + summary.json
"""
import json, os, re, shutil, subprocess, sys, time
from datetime import date, timedelta
from pathlib import Path

CATALOG = Path.home() / ".coros-mcp-skill-gateway-ts" / "us" / "tool-catalog.json"
OUT = Path(__file__).parent / "smoke_output"
TIMEOUT = 60
# read-only-annotated but bulk/binary: fetch only URLs variant, skip the binary download
SKIP_HEAVY = {"downloadActivityFitFiles"}
NPX = shutil.which("npx") or shutil.which("npx.cmd") or r"C:\Program Files\nodejs\npx.cmd"


def call(tool, args):
    cmd = [NPX, "-y", "coros-mcp", "call-tool", "--tool", tool, "--arguments-json", json.dumps(args)]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return dict(ok=False, error=f"timeout {TIMEOUT}s", text="", raw="", secs=TIMEOUT)
    raw = (p.stdout or "") + (("\n[stderr]\n" + p.stderr) if p.stderr.strip() else "")
    text, is_err = "", p.returncode != 0
    try:
        j = json.loads(p.stdout)
        is_err = is_err or bool(j.get("isError"))
        text = "\n".join(c.get("text", "") for c in j.get("content", []) if c.get("type") == "text")
    except Exception:
        text = p.stdout.strip()
    if re.match(r"^\s*(Tool not found|Error)", text) or "Tool not found" in raw[:400]:
        is_err = True
    return dict(ok=not is_err, error=(text or p.stderr)[:400] if is_err else "",
                text=text, raw=raw, secs=round(time.time() - t0, 1))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tools = json.loads(CATALOG.read_text(encoding="utf-8"))["tools"]
    today = date.today()
    d7, d0 = (today - timedelta(days=7)).strftime("%Y%m%d"), today.strftime("%Y%m%d")
    d30 = (today - timedelta(days=30)).strftime("%Y%m%d")
    ctx = {}

    # discover a real running activity first
    r = call("querySportRecords", {"startDate": d30, "endDate": d0, "limit": 50})
    txt = r["text"]
    try:
        v = json.loads(txt)
        txt = v if isinstance(v, str) else txt
    except Exception:
        pass
    for m in re.finditer(r"LabelId: (\d+) \| SportType: (\d+)", txt):
        if m.group(2) == "100":
            ctx["labelId"], ctx["sportType"] = m.group(1), 100
            break
    mt = re.search(r"startTimestamp=(\d+) \| endTimestamp=(\d+)", txt)
    if mt:
        ctx["start"], ctx["end"] = int(mt.group(1)), int(mt.group(2))
    print("context:", ctx)

    def args_for(name):
        lab = {"labelId": ctx.get("labelId", ""), "sportType": ctx.get("sportType", 100)}
        table = {
            "querySportRecords": {"startDate": d30, "endDate": d0, "limit": 200},
            "queryActivityLapData": lab,
            "getActivityDetail": lab,
            "analyzeActivityDetail": {**lab, "focus": "cadence stride ground contact"},
            "queryCustomActivityLapData": {**lab, "startTimestamp": ctx.get("start", 0) + 300,
                                           "endTimestamp": ctx.get("start", 0) + 900},
            "queryActivityFitFileDownloadUrls": {"labelId": ctx.get("labelId", ""), "sportType": 100, "limit": 1},
            "querySleepData": {"startDate": d7, "endDate": d0},
            "querySleepHrv": {"days": 7},
            "queryHealthCheckTimeSeries": {"days": 7},
            "queryStressTimeSeries": {"days": 1},
            "queryTrainingSchedule": {"startDate": d0, "endDate": (today + timedelta(days=7)).strftime("%Y%m%d")},
            "queryTrainingPlanLibrary": {"statusList": [0, 1, 2]},
            "queryAvgHeartRate": {"days": 7},
            "queryRestingHeartRate": {"days": 7},
            "queryStressLevel": {"days": 7},
            "queryDailyHealthData": {"days": 7},
            "queryTrainingLoadAssessment": {"days": 7},
        }
        return table.get(name, {})

    summary, skipped = [], []
    cache = {}
    for t in tools:
        name, ann = t["name"], t.get("annotations", {})
        if not ann.get("readOnlyHint"):
            skipped.append({"tool": name, "reason": "write/side-effect, not smoke-tested"})
            continue
        if name in SKIP_HEAVY:
            skipped.append({"tool": name, "reason": "binary FIT download (50/day quota), not smoke-tested"})
            continue
        args = args_for(name)
        try:
            # plan/workout id dependent tools: discover an id
            if name == "queryTrainingPlanDetails":
                lib = cache.get("plans") or call("queryTrainingPlanLibrary", {"statusList": [0, 1, 2]})
                cache["plans"] = lib
                m = re.search(r"(?:Plan ?ID|planId)\W+(\d{10,})", lib["text"], re.I)
                if not m:
                    skipped.append({"tool": name, "reason": "no plan id available"}); continue
                args = {"planId": m.group(1)}
            if name == "queryWorkoutDetails":
                lib = call("queryWorkoutLibrary", {})
                m = re.search(r"(?:Workout ?ID|workoutId)\W+(\d{10,})", lib["text"], re.I)
                if not m:
                    skipped.append({"tool": name, "reason": "no workout id available"}); continue
                args = {"workoutId": m.group(1)}
            if name == "queryScheduledWorkoutDetails":
                skipped.append({"tool": name, "reason": "needs idInPlan of an MCP-created workout"}); continue
            if name.endswith(("ActivityDetail", "LapData")) and not ctx.get("labelId"):
                skipped.append({"tool": name, "reason": "no running labelId found"}); continue
            r = call(name, args)
        except Exception as e:  # never stop the run
            r = dict(ok=False, error=repr(e), text="", raw="", secs=0)
        (OUT / f"{name}.txt").write_text(
            f"ARGS: {json.dumps(args)}\nOK: {r['ok']}\n\n{r['raw']}", encoding="utf-8")
        text = r["text"].lstrip()
        summary.append(dict(tool=name, args=args, works=r["ok"], error=r["error"],
                            secs=r["secs"], json_string_encoded=text.startswith('"'),
                            preview=text[:300]))
        print(f"{'OK  ' if r['ok'] else 'FAIL'} {name} ({r['secs']}s) {r['error'][:80]}")
    (OUT / "summary.json").write_text(json.dumps(
        {"date": str(today), "context": ctx, "results": summary, "not_tested": skipped},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{sum(s['works'] for s in summary)}/{len(summary)} ok; {len(skipped)} skipped")


if __name__ == "__main__":
    main()
