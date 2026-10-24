"""Season plan set-up: profile checklist, preview of the season outline, create, weekly refresh; tune-up races.

GET  /plan/preview?distance=&target_time=   season outline that would be created (nothing saved)
POST /plan/create                           save distance/target time to the Goal Profile, create the season plan
POST /plan/refresh                          regenerate upcoming days from actual training (past kept)
POST /profile/races                         add a tune-up race      POST /profile/races/<id>/delete
"""
from datetime import date
from typing import Any, Dict, List, Optional

from flask import Flask, redirect, render_template, request, url_for

from app.data.queries import (delete_tune_up_race, get_tune_up_races, get_user_profile, save_tune_up_race,
                              save_user_profile)
from app.engine.plan_bundle import create_training_plan, preview_season_plan, refresh_plan
from app.engine.plan_view import build_plan_view
from app.engine.planner import RACE_DISTANCE_KM, ProfileIncompleteError, parse_target_minutes

GOAL_DISTANCES = ["5K", "10K", "Half Marathon", "Marathon", "50K Ultra", "100K Ultra"]
TUNE_UP_DISTANCES = ["5K", "10K", "Half Marathon", "Marathon"]


def _answered(v) -> bool:
    return v is not None


def setup_checklist(profile: Dict[str, Any], tune_ups: List[Dict[str, Any]], today: date) -> Dict[str, Any]:
    """What the plan needs from the Goal Profile, section by section."""
    try:
        race_ok = bool(profile.get("race_date")) and date.fromisoformat(str(profile["race_date"])[:10]) > today
    except ValueError:
        race_ok = False
    items = [
        {"key": "race", "label": "Goal race", "anchor": "goal",
         "ok": race_ok and bool(profile.get("race_distance_type")),
         "detail": (f"{profile.get('race_distance_type')} on {profile.get('race_date')}" if race_ok
                    else "Race distance and a future race date")},
        {"key": "availability", "label": "Availability & constraints", "anchor": "availability",
         "ok": bool(profile.get("available_days")) and profile.get("weekly_hours_available") not in (None, ""),
         "detail": (f"{profile.get('available_days')} · {profile.get('weekly_hours_available')} h/week"
                    if profile.get("available_days") else "Training days and weekly hours")},
        {"key": "history", "label": "Medical & physical history", "anchor": "history",
         "ok": _answered(profile.get("injury_history")) and _answered(profile.get("current_niggles")),
         "detail": "Injury history and current niggles (\"None\" is an answer)"},
        {"key": "races", "label": "Tune-up races (optional)", "anchor": "races", "ok": True,
         "detail": f"{len(tune_ups)} tune-up race{'s' if len(tune_ups) != 1 else ''} planned" if tune_ups
                   else "None added: add half marathons or 10Ks you plan to run on the way"},
    ]
    return {"items": items, "ready": all(i["ok"] for i in items)}


def _overrides(source) -> Dict[str, Any]:
    out = {}
    d = (source.get("distance") or "").strip()
    if d in GOAL_DISTANCES:
        out["race_distance_type"] = d
    t = (source.get("target_time") or "").strip()
    if t:
        out["target_time_str"] = t
    return out


def register_season_routes(app: Flask) -> None:

    def _db():
        return app.config.get("DATABASE_PATH")

    def _today() -> date:
        return app.config.get("TODAY") or date.today()

    @app.route("/plan/preview", methods=["GET"])
    def plan_preview():
        ov = _overrides(request.args)
        target = ov.get("target_time_str")
        if target and parse_target_minutes(target, ov.get("race_distance_type") or
                                           get_user_profile(db_path=_db()).get("race_distance_type") or "") is None:
            return redirect(url_for("plan_view", new=1, error="Target time must look like 3:30:00 (or 45:00 for a 10K)."))
        try:
            plan = preview_season_plan(db_path=_db(), today=_today(), overrides=ov)
        except ProfileIncompleteError:
            return redirect(url_for("plan_view", profile_incomplete=1))
        vm = build_plan_view({**plan, "plan_kind": "season"}, today=_today())
        return render_template("plan_preview.html", plan=plan, vm=vm, overrides=ov, active_page="plan")

    @app.route("/plan/create", methods=["POST"])
    def plan_create():
        ov = _overrides(request.form)
        if ov:
            profile = get_user_profile(db_path=_db())
            save_user_profile({**{k: profile.get(k) for k in ("race_distance_type", "race_date", "target_time_str",
                                                               "weekly_hours_available", "available_days",
                                                               "injury_history", "current_niggles")}, **ov},
                              db_path=_db())
        try:
            create_training_plan(db_path=_db(), today=_today(), season=True)
        except ProfileIncompleteError:
            return redirect(url_for("plan_view", profile_incomplete=1))
        return redirect(url_for("plan_view", created=1))

    @app.route("/plan/refresh", methods=["POST"])
    def plan_refresh():
        try:
            res = refresh_plan(db_path=_db(), today=_today())
        except (ValueError, ProfileIncompleteError) as err:
            return redirect(url_for("plan_view", error=str(err)))
        return redirect(url_for("plan_view", refreshed=res["added"]))

    @app.route("/profile/races", methods=["POST"])
    def tune_up_add():
        f = request.form
        dist = f.get("tu_distance")
        try:
            day = date.fromisoformat((f.get("tu_race_date") or "").strip())
        except ValueError:
            return redirect(url_for("profile", race_error="Choose the tune-up race date.") + "#races")
        if dist not in TUNE_UP_DISTANCES:
            return redirect(url_for("profile", race_error="Choose the tune-up race distance.") + "#races")
        if day <= _today():
            return redirect(url_for("profile", race_error="The tune-up race date must be in the future.") + "#races")
        t = (f.get("tu_target_time") or "").strip()
        if t and parse_target_minutes(t, dist) is None:
            return redirect(url_for("profile", race_error="Target time must look like 1:39:00.") + "#races")
        save_tune_up_race({"name": f.get("name"), "race_date": day.isoformat(), "distance": dist,
                           "priority": f.get("priority"), "target_time_str": t, "mode": f.get("mode")},
                          db_path=_db())
        return redirect(url_for("profile", race_saved=1) + "#races")

    @app.route("/profile/races/<int:race_id>/delete", methods=["POST"])
    def tune_up_delete(race_id: int):
        delete_tune_up_race(race_id, db_path=_db())
        return redirect(url_for("profile") + "#races")
