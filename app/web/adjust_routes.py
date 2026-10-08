"""Session adjustment routes: swap for an alternative / missed + rebalance, with preview and explicit confirm.

GET  /session/<id>/adjust            choose a reason, then an alternative or "missed - rebalance my week"
GET  /session/<id>/adjust/preview    before -> after per day; writes NOTHING
POST /session/<id>/adjust            confirm: recompute, check the preview token, then save
All pages work without JavaScript; Cancel links return to /plan.
"""
from datetime import date

from flask import Flask, abort, redirect, render_template, request, url_for

from app.data.queries import apply_session_adjustments, get_active_training_plan, get_user_profile
from app.engine import reschedule as rs


def register_adjust_routes(app: Flask) -> None:

    def _today() -> date:
        return app.config.get("TODAY") or date.today()   # TODAY is a test hook

    def _load(session_id: str):
        db = app.config.get("DATABASE_PATH")
        plan = get_active_training_plan(db_path=db)
        if not plan:
            abort(404)
        session = next((s for s in plan["sessions"] if s["id"] == session_id), None)
        if session is None:
            abort(404)
        return db, plan, session

    def _args(source):
        reason = source.get("reason")
        reason = reason if reason in rs.REASON_LABELS else None
        note = (source.get("note") or "").strip()[:300]
        return reason, note, source.get("mode"), source.get("option")

    def _propose(db, plan, session_id, mode, option, reason, note):
        today = _today()
        if mode == "swap":
            return rs.propose_swap(plan, session_id, option or "", reason, note, today=today)
        if mode == "missed":
            profile = get_user_profile(db_path=db)
            return rs.propose_missed(plan, session_id, reason, note, today=today,
                                     available_days=profile.get("available_days"))
        raise rs.AdjustError("Choose an alternative or 'Missed - rebalance my week'.")

    @app.route("/session/<session_id>/adjust", methods=["GET"])
    def session_adjust(session_id: str):
        db, plan, session = _load(session_id)
        reason, note, _, _ = _args(request.args)
        today = _today()
        actions = {"swap": rs.can_swap(session, today), "missed": rs.can_mark_missed(session, today)}
        options = rs.swap_options(session, reason) if (reason and actions["swap"]) else []
        if options:
            # Only offer alternatives that keep the guardrails (no violation that skipping alone would not cause)
            valid = []
            for o in options:
                try:
                    if rs.propose_swap(plan, session_id, o["key"], reason, note, today=today)["valid"]:
                        valid.append(o)
                except rs.AdjustError:
                    pass
            if valid and not any(o["recommended"] for o in valid):
                valid[0]["recommended"] = True
            options = valid
        return render_template(
            "session_adjust.html", session=session, session_text=rs.describe(session),
            date_label=rs.day_label(session), reasons=rs.REASONS, reason=reason, note=note,
            actions=actions, options=options, error=request.args.get("error"), active_page="plan")

    @app.route("/session/<session_id>/adjust/preview", methods=["GET"])
    def session_adjust_preview(session_id: str):
        db, plan, session = _load(session_id)
        reason, note, mode, option = _args(request.args)
        if not reason:
            return redirect(url_for("session_adjust", session_id=session_id, error="reason"))
        try:
            proposal = _propose(db, plan, session_id, mode, option, reason, note)
        except rs.AdjustError as err:
            return render_template("session_adjust_preview.html", session=session, proposal=None, error=str(err),
                                   reason=reason, note=note, active_page="plan"), 400
        return render_template("session_adjust_preview.html", session=session, proposal=proposal, error=None,
                               option=option, reason=reason, note=note, stale=request.args.get("stale") == "1",
                               active_page="plan")

    @app.route("/session/<session_id>/adjust", methods=["POST"])
    def session_adjust_confirm(session_id: str):
        db, plan, session = _load(session_id)
        reason, note, mode, option = _args(request.form)
        if not reason:
            return redirect(url_for("session_adjust", session_id=session_id, error="reason"))
        try:
            proposal = _propose(db, plan, session_id, mode, option, reason, note)
        except rs.AdjustError as err:
            return render_template("session_adjust_preview.html", session=session, proposal=None, error=str(err),
                                   reason=reason, note=note, active_page="plan"), 400
        if not proposal["valid"]:
            return render_template("session_adjust_preview.html", session=session, proposal=proposal, error=None,
                                   option=option, reason=reason, note=note, active_page="plan"), 400
        if request.form.get("token") != proposal["token"]:
            # The plan changed since the preview: show the current proposal again instead of saving blindly
            return redirect(url_for("session_adjust_preview", session_id=session_id, mode=mode, option=option or "",
                                    reason=reason, note=note, stale="1"))
        apply_session_adjustments(proposal, db_path=db)
        return redirect(url_for("plan_view", adjusted=mode))
