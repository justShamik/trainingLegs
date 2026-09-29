"""Flask Application Factory & Web Routes."""
import os
from flask import Flask, render_template, request, jsonify, redirect, url_for, abort
from app.cli import sync_cli
from app.data.db import init_db
from app.data.queries import (
    get_dashboard_summary, get_recent_activities, get_trend_charts_data,
    get_activity_detail, get_user_profile, save_user_profile,
    save_training_plan, get_active_training_plan, delete_active_training_plan,
    update_session_status, calculate_weekly_compliance, auto_match_activities_to_sessions,
    save_block_summary, get_block_summaries, save_strength_workout,
    get_active_strength_workout, update_strength_workout_status
)
from app.data.sync import perform_sync
from app.mcp_client.coros_client import CorosMCPClient
from app.engine.planner import TrainingPlanner
from app.engine.tracking import detect_overtraining_risk, generate_post_run_feedback
from app.engine.strength import StrengthEngine
from app.llm.context_builder import build_runner_context
from app.llm.gemini_cli import GeminiCLIWrapper

def create_app(db_path: str = None) -> Flask:
    """Create and configure Flask Application instance."""
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    
    if db_path:
        app.config["DATABASE_PATH"] = db_path
        os.environ["DATABASE_PATH"] = db_path
        
    init_db(db_path)
    app.cli.add_command(sync_cli)
    
    @app.route("/")
    def index():
        current_db = app.config.get("DATABASE_PATH")
        days = request.args.get("days", default=30, type=int)
        summary = get_dashboard_summary(db_path=current_db)
        recent_activities = get_recent_activities(days=days, limit=50, db_path=current_db)
        trends = get_trend_charts_data(db_path=current_db)
        sync_msg = request.args.get("sync_msg")
        sync_status = request.args.get("sync_status")
        
        coros_client = CorosMCPClient()
        coros_auth = coros_client.validate_token_status()

        return render_template(
            "dashboard.html",
            summary=summary,
            recent_activities=recent_activities,
            trends=trends,
            sync_msg=sync_msg,
            sync_status=sync_status,
            selected_days=days,
            coros_auth=coros_auth,
            active_page="dashboard"
        )

    @app.route("/coros/login", methods=["POST", "GET"])
    def coros_login():
        client = CorosMCPClient()
        launched = client.trigger_login_flow()
        msg = "🔑 COROS browser login window opened. Please complete authentication in the browser window, then click Sync!" if launched else "🔑 Could not launch login command automatically. Please run 'npx coros-mcp login' in your terminal."
        status = "success" if launched else "error"
        return redirect(url_for("index", sync_msg=msg, sync_status=status))

    @app.route("/sync", methods=["POST"])
    def sync_data():
        current_db = app.config.get("DATABASE_PATH")
        is_full = request.form.get("full") == "1"
        success, count, msg, duration = perform_sync(full=is_full, db_path=current_db)
        status_code = "success" if success else "error"
        return redirect(url_for("index", sync_msg=msg, sync_status=status_code))

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
        coros_client = CorosMCPClient()
        coros_auth = coros_client.validate_token_status()
        
        return render_template(
            "plan.html",
            plan=active_plan,
            compliance=compliance,
            overtraining=overtraining,
            coros_auth=coros_auth,
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
        act_dist = float(data["actual_distance_km"]) if data.get("actual_distance_km") else None
        act_dur = float(data["actual_duration_min"]) if data.get("actual_duration_min") else None
        act_pace = float(data["actual_avg_pace_s_km"]) if data.get("actual_avg_pace_s_km") else None
        act_hr = int(data["actual_avg_hr"]) if data.get("actual_avg_hr") else None

        # Build post-run feedback string
        feedback = generate_post_run_feedback(
            {"session_type": data.get("session_type", "Easy Aerobic"), "distance_km": act_dist, "status": status},
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
        if request.method == "POST":
            profile_data = {
                "race_distance_type": request.form.get("race_distance_type", "Marathon"),
                "race_date": request.form.get("race_date"),
                "target_time_str": request.form.get("target_time_str"),
                "weekly_hours_available": request.form.get("weekly_hours_available", 8.0),
                "available_days": request.form.get("available_days"),
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
            response_text = wrapper.ask_coach(question=question, runner_context=runner_context)
            return jsonify({"response": response_text})

        return render_template("chat.html", active_page="chat")

    @app.errorhandler(404)
    def handle_not_found(e):
        return render_template("error.html", error_title="Resource Not Found", error_message="The requested activity or page could not be located."), 404

    @app.errorhandler(Exception)
    def handle_global_error(e):
        if app.testing:
            raise e
        return render_template("error.html", error_title="Application Error", error_message="An internal condition occurred while loading data."), 500
        
    return app
