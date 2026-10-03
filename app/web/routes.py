"""Flask Application Factory & Web Routes."""
import logging
import os
from datetime import date
from urllib.parse import urlsplit, urlencode, parse_qsl, urlunsplit
from flask import Flask, render_template, request, jsonify, redirect, url_for, abort
from werkzeug.exceptions import HTTPException
from app.cli import sync_cli, races_refresh_command
from app.data.db import init_db
from app.data.queries import (
    get_dashboard_summary, get_recent_activities, get_trend_charts_data,
    get_activity_detail, get_user_profile, save_user_profile,
    save_training_plan, get_active_training_plan, delete_active_training_plan,
    update_session_status, calculate_weekly_compliance, auto_match_activities_to_sessions,
    save_block_summary, get_block_summaries, save_strength_workout,
    get_active_strength_workout, update_strength_workout_status, save_gemini_api_key,
    get_plan_session, get_today_summary, get_sync_status
)
from app.races import service as race_service
from app.data.sync import perform_sync
from app.mcp_client.coros_client import CorosMCPClient
from app.engine.planner import TrainingPlanner
from app.engine.tracking import detect_overtraining_risk, generate_post_run_feedback
from app.engine.strength import StrengthEngine
from app.engine.targets import describe_target
from app.llm.context_builder import build_runner_context
from app.llm.gemini_cli import GeminiCLIWrapper

logger = logging.getLogger("coach.web.routes")

RESULT_PARAMS = ("sync_msg", "sync_status", "race_msg", "race_status")


def safe_next(target, default: str = "/") -> str:
    """Return target if it is a same-site path ("/..."), else default (blocks open redirects)."""
    if not target or not isinstance(target, str):
        return default
    target = target.strip()
    if not target.startswith("/") or target.startswith("//") or "\\" in target:
        return default
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or any(ord(c) < 32 for c in target):
        return default
    return target


def redirect_with(target: str, **params):
    """Redirect to a local path, replacing any previous result params with the new ones."""
    parts = urlsplit(target)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in RESULT_PARAMS]
    query += [(k, v) for k, v in params.items() if v is not None]
    return redirect(urlunsplit(("", "", parts.path or "/", urlencode(query), parts.fragment)))


def create_app(db_path: str = None) -> Flask:
    """Create and configure Flask Application instance."""
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    
    if db_path:
        app.config["DATABASE_PATH"] = db_path
        os.environ["DATABASE_PATH"] = db_path
        
    init_db(db_path)
    from app.logging_config import setup_logging; setup_logging(app)  # structured logs -> logs/app.log
    app.cli.add_command(sync_cli)
    app.cli.add_command(races_refresh_command)
    from app.analytics import init_analytics; init_analytics(app)  # self-hosted analytics (ADR-006)
    app.jinja_env.filters["describe_target"] = describe_target

    @app.context_processor
    def inject_coros_auth():
        """Supply coros_auth to every template (navbar badge); file check only, no subprocess."""
        try:
            return {"coros_auth": CorosMCPClient().validate_token_status()}
        except Exception:
            return {"coros_auth": {"is_authenticated": False, "token_exists": False, "status_code": "UNKNOWN", "message": "COROS status unavailable"}}
    
    @app.route("/")
    def home():
        current_db = app.config.get("DATABASE_PATH")
        today = get_today_summary(db_path=current_db)
        sync_status = get_sync_status(db_path=current_db)
        try:
            races = race_service.get_races_for_home(db_path=current_db)
        except Exception as err:  # the race list must never take the home page down
            logger.warning("races unavailable on home page: %s", err)
            races = {"races": [], "watchlist": [], "ncr_50k": [], "last_checked_at": None,
                     "needs_refresh": False, "as_of": None, "error": "Race list unavailable right now."}
        try:
            d = date.fromisoformat(str(today["date"])[:10])
            date_display = f"{d:%A}, {d.day} {d:%B}"
        except (KeyError, ValueError):
            date_display = ""
        return render_template(
            "home.html",
            today=today,
            date_display=date_display,
            sync=sync_status,
            races=races,
            sync_msg=request.args.get("sync_msg"),
            sync_result=request.args.get("sync_status"),
            race_msg=request.args.get("race_msg"),
            race_status=request.args.get("race_status"),
            active_page="home",
        )

    @app.route("/dashboard")
    def index():
        current_db = app.config.get("DATABASE_PATH")
        days = request.args.get("days", default=30, type=int)
        summary = get_dashboard_summary(db_path=current_db)
        recent_activities = get_recent_activities(days=days, limit=50, db_path=current_db)
        trends = get_trend_charts_data(db_path=current_db)
        sync_msg = request.args.get("sync_msg")
        sync_status = request.args.get("sync_status")

        return render_template(
            "dashboard.html",
            summary=summary,
            recent_activities=recent_activities,
            trends=trends,
            sync_msg=sync_msg,
            sync_status=sync_status,
            selected_days=days,
            active_page="dashboard"
        )

    @app.route("/coros/login", methods=["POST"])
    def coros_login():
        client = CorosMCPClient()
        launched = client.trigger_login_flow()
        msg = "🔑 COROS browser login window opened. Please complete authentication in the browser window, then click Sync!" if launched else "🔑 Could not launch login command automatically. Please run 'npx coros-mcp login' in your terminal."
        status = "success" if launched else "error"
        target = safe_next(request.form.get("next"), url_for("home"))
        return redirect_with(target, sync_msg=msg, sync_status=status)

    @app.route("/sync", methods=["POST"])
    def sync_data():
        current_db = app.config.get("DATABASE_PATH")
        is_full = request.form.get("full") == "1"
        success, count, msg, duration = perform_sync(full=is_full, db_path=current_db)
        status_code = "success" if success else "error"
        target = safe_next(request.form.get("next"), url_for("home"))
        return redirect_with(target, sync_msg=msg, sync_status=status_code)

    @app.route("/races/refresh", methods=["POST"])
    def races_refresh():
        current_db = app.config.get("DATABASE_PATH")
        try:
            summary = race_service.refresh_races(db_path=current_db)
            checked, changed, errors = summary.get("checked", 0), summary.get("changed", 0), summary.get("errors", 0)
            msg = (f"Checked {checked} race website{'s' if checked != 1 else ''}: "
                   f"{changed} status change{'s' if changed != 1 else ''}"
                   + (f", {errors} site{'s' if errors != 1 else ''} could not be read" if errors else "") + ".")
            status = "success" if checked and errors < checked else ("error" if errors else "success")
            logger.info('action_result action=races_refresh status=%s message="%s"', status, msg)
        except Exception as err:
            logger.warning("races_refresh failed: %s: %s", type(err).__name__, err)
            msg, status = f"Race check failed ({type(err).__name__}). Saved race data is unchanged.", "error"
        return redirect_with(url_for("home") + "#races", race_msg=msg, race_status=status)

    @app.route("/activity/<activity_id>")
    def activity_detail(activity_id: str):
        current_db = app.config.get("DATABASE_PATH")
        activity = get_activity_detail(activity_id, db_path=current_db)
        if not activity:
            abort(404)
        return render_template("activity_detail.html", activity=activity, active_page="activity")

    @app.route("/plan", methods=["GET"])
    def plan_view():
        current_db = app.config.get("DATABASE_PATH")
        
        # Auto-match completed COROS activities on page load to update workout adherence ratings
        auto_match_activities_to_sessions(db_path=current_db)
        
        active_plan = get_active_training_plan(db_path=current_db)
        compliance = calculate_weekly_compliance(db_path=current_db)
        overtraining = detect_overtraining_risk(db_path=current_db)
        from app.engine.plan_view import build_plan_view
        plan_vm = build_plan_view(active_plan)

        return render_template(
            "plan.html",
            plan=active_plan,
            plan_vm=plan_vm,
            compliance=compliance,
            overtraining=overtraining,
            active_page="plan"
        )

    @app.route("/plan/generate", methods=["POST"])
    def plan_generate():
        current_db = app.config.get("DATABASE_PATH")
        is_deload = request.form.get("is_deload") == "1"
        planner = TrainingPlanner(db_path=current_db)
        generated_plan = planner.generate_plan(is_deload=is_deload)
        save_training_plan(generated_plan, db_path=current_db)
        return redirect(url_for("plan_view"))

    @app.route("/plan/discard", methods=["POST"])
    def plan_discard():
        current_db = app.config.get("DATABASE_PATH")
        delete_active_training_plan(db_path=current_db)
        return redirect(url_for("plan_view"))


    @app.route("/session/update", methods=["POST"])
    def session_update():
        current_db = app.config.get("DATABASE_PATH")
        data = request.form if request.form else (request.get_json(silent=True) or {})
        session_id = data.get("session_id")
        if not session_id:
            return jsonify({"error": "Missing session_id"}), 400

        status = data.get("status", "Completed")
        user_notes = data.get("user_notes")
        try:
            act_dist = float(data["actual_distance_km"]) if data.get("actual_distance_km") else None
            act_dur = float(data["actual_duration_min"]) if data.get("actual_duration_min") else None
            act_pace = float(data["actual_avg_pace_s_km"]) if data.get("actual_avg_pace_s_km") else None
            act_hr = int(float(data["actual_avg_hr"])) if data.get("actual_avg_hr") else None
        except (TypeError, ValueError):
            return jsonify({"error": "Actual metrics must be numeric"}), 400

        planned = get_plan_session(session_id, db_path=current_db) or {}
        if not planned.get("session_type") and data.get("session_type"):
            planned["session_type"] = data.get("session_type")

        # Build post-run feedback string against the real prescribed session
        feedback = generate_post_run_feedback(
            {**planned, "status": status},
            {"actual_distance_km": act_dist, "actual_duration_min": act_dur, "actual_avg_pace_s_km": act_pace, "actual_avg_hr": act_hr, "status": status}
        )

        update_session_status(
            session_id=session_id,
            status=status,
            user_notes=user_notes,
            actual_distance_km=act_dist,
            actual_duration_min=act_dur,
            actual_avg_pace_s_km=act_pace,
            actual_avg_hr=act_hr,
            post_run_feedback=feedback,
            db_path=current_db
        )

        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"status": "success", "feedback": feedback})

        return redirect(url_for("plan_view"))

    @app.route("/session/auto-match", methods=["POST"])
    def session_auto_match():
        current_db = app.config.get("DATABASE_PATH")
        matched_count = auto_match_activities_to_sessions(db_path=current_db)
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"status": "success", "matched_count": matched_count})
        return redirect(url_for("plan_view"))

    @app.route("/block-summary", methods=["GET"])
    def block_summary():
        current_db = app.config.get("DATABASE_PATH")
        blocks = get_block_summaries(db_path=current_db)
        compliance = calculate_weekly_compliance(db_path=current_db)
        overtraining = detect_overtraining_risk(db_path=current_db)
        active_plan = get_active_training_plan(db_path=current_db)
        return render_template(
            "block_summary.html",
            blocks=blocks,
            compliance=compliance,
            overtraining=overtraining,
            plan=active_plan,
            active_page="block_summary"
        )

    @app.route("/strength", methods=["GET"])
    def strength_view():
        current_db = app.config.get("DATABASE_PATH")
        workout = get_active_strength_workout(db_path=current_db)
        if not workout:
            engine = StrengthEngine(db_path=current_db)
            workout = engine.generate_workout()
            save_strength_workout(workout, db_path=current_db)
            workout = get_active_strength_workout(db_path=current_db)
        return render_template("strength.html", workout=workout, active_page="strength")

    @app.route("/strength/generate", methods=["POST"])
    def strength_generate():
        current_db = app.config.get("DATABASE_PATH")
        phase = request.form.get("phase", "Base")
        engine = StrengthEngine(db_path=current_db)
        workout = engine.generate_workout(phase=phase)
        save_strength_workout(workout, db_path=current_db)
        return redirect(url_for("strength_view"))

    @app.route("/strength/update", methods=["POST"])
    def strength_update():
        current_db = app.config.get("DATABASE_PATH")
        workout_id = request.form.get("workout_id")
        status = request.form.get("status", "Completed")
        if workout_id:
            update_strength_workout_status(workout_id, status, db_path=current_db)
        return redirect(url_for("strength_view"))



    @app.route("/profile", methods=["GET", "POST"])
    def profile():
        current_db = app.config.get("DATABASE_PATH")
        saved_success = False
        if request.method == "POST" and "gemini_api_key" in request.form and "race_distance_type" not in request.form:
            # Key-only update from the chat page: never touch the rest of the profile
            save_gemini_api_key(request.form.get("gemini_api_key", "").strip(), db_path=current_db)
            return jsonify({"status": "success"})

        if request.method == "POST":
            try:
                weekly_hours = float(request.form.get("weekly_hours_available") or 8.0)
            except ValueError:
                weekly_hours = 8.0
            profile_data = {
                "race_distance_type": request.form.get("race_distance_type", "Marathon"),
                "race_date": request.form.get("race_date"),
                "target_time_str": request.form.get("target_time_str"),
                "weekly_hours_available": weekly_hours,
                "available_days": request.form.get("available_days") or "Mon,Tue,Thu,Sat,Sun",
                "injury_history": request.form.get("injury_history"),
                "current_niggles": request.form.get("current_niggles")
            }
            save_user_profile(profile_data, db_path=current_db)
            saved_success = True

        user_profile = get_user_profile(db_path=current_db)
        return render_template("profile.html", profile=user_profile, saved_success=saved_success, active_page="profile")

    @app.route("/chat", methods=["GET", "POST"])
    def chat():
        current_db = app.config.get("DATABASE_PATH")
        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            question = data.get("question", "").strip()
            if not question:
                return jsonify({"response": "Please enter a question for your coach."}), 400

            runner_context = build_runner_context(db_path=current_db)
            wrapper = GeminiCLIWrapper()
            response_text = wrapper.ask_coach(question=question, runner_context=runner_context, db_path=current_db)
            return jsonify({"response": response_text})

        return render_template("chat.html", active_page="chat")

    @app.errorhandler(404)
    def handle_not_found(e):
        return render_template("error.html", error_title="Resource Not Found", error_message="The requested activity or page could not be located."), 404

    @app.errorhandler(Exception)
    def handle_global_error(e):
        if isinstance(e, HTTPException):
            return e
        if app.testing:
            raise e
        return render_template("error.html", error_title="Application Error", error_message="An internal condition occurred while loading data."), 500
        
    return app
