"""Heart-rate zones from a 30-minute field test.

GET  /zones                  protocol, current zones, how to enter them in COROS, analyse a run, history
POST /zones/analyse          analyse a synced run as the test (fetches its per-second file from COROS)
POST /zones/<id>/entered     record that the zones were entered in COROS
POST /zones/<id>/delete      remove a test result
"""
import logging

from flask import Flask, redirect, render_template, request, url_for

from app.analysis import hr_zones as hz
from app.analysis import zone_service as zs

logger = logging.getLogger("coach.web.zones")


def register_zone_routes(app: Flask) -> None:

    def _db():
        return app.config.get("DATABASE_PATH")

    @app.route("/zones", methods=["GET"])
    def zones_view():
        db = _db()
        tests = zs.get_tests(db_path=db)
        selected = request.args.get("test", type=int)
        latest = next((t for t in tests if t["id"] == selected), tests[0] if tests else None)
        return render_template(
            "zones.html", tests=tests, latest=latest, current=zs.current_lthr(db_path=db),
            due=zs.test_due(db_path=db), candidates=zs.list_candidates(db_path=db),
            sensors=hz.SENSORS, sem=hz.SEM_BPM, error=request.args.get("error"),
            saved=request.args.get("saved"), active_page="zones")

    @app.route("/zones/analyse", methods=["POST"])
    def zones_analyse():
        activity_id = (request.form.get("activity_id") or "").strip()
        sensor = request.form.get("sensor")
        temp_raw = (request.form.get("temperature_c") or "").strip()
        if not activity_id:
            return redirect(url_for("zones_view", error="Choose the run you did the test in.") + "#analyse")
        if sensor not in hz.SENSORS:
            return redirect(url_for("zones_view", error="Say whether you wore a chest strap or used wrist HR.") + "#analyse")
        try:
            temp = float(temp_raw) if temp_raw else None
            if temp is not None and not -10 <= temp <= 50:
                raise ValueError
        except ValueError:
            return redirect(url_for("zones_view", error="Temperature must be a number in °C.") + "#analyse")
        try:
            test_id = zs.analyse_activity(activity_id, sensor=sensor, temperature_c=temp, db_path=_db())
        except hz.ZoneTestError as err:
            return redirect(url_for("zones_view", error=str(err)) + "#analyse")
        except Exception as err:
            logger.warning("zone test analysis failed: %s: %s", type(err).__name__, err)
            return redirect(url_for("zones_view", error=f"Analysis failed ({type(err).__name__}). Nothing was saved.")
                            + "#analyse")
        logger.info("action_result action=zone_test status=success test_id=%s", test_id)
        return redirect(url_for("zones_view", test=test_id) + "#result")

    @app.route("/zones/<int:test_id>/entered", methods=["POST"])
    def zones_entered(test_id: int):
        zs.mark_entered(test_id, db_path=_db())
        return redirect(url_for("zones_view", test=test_id, saved="entered") + "#result")

    @app.route("/zones/<int:test_id>/delete", methods=["POST"])
    def zones_delete(test_id: int):
        zs.delete_test(test_id, db_path=_db())
        return redirect(url_for("zones_view", saved="deleted"))
