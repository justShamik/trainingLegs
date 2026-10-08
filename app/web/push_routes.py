"""Send planned runs to COROS. GET shows the preview (writes nothing); POST sends only what was confirmed."""
import logging

from flask import Flask, render_template, request

from app.coros_push import service as push_service

logger = logging.getLogger("coach.web.push")
DAY_CHOICES = (7, 14, 28, 35)


def register_push_routes(app: Flask) -> None:

    def _days(source) -> int:
        d = source.get("days", type=int) or 14
        return d if d in DAY_CHOICES else 14

    def _today():
        return app.config.get("TODAY")       # test hook; None = real today

    @app.route("/plan/push", methods=["GET"])
    def plan_push_preview():
        days = _days(request.args)
        preview = push_service.build_preview(db_path=app.config.get("DATABASE_PATH"), today=_today(), days=days)
        return render_template("push_preview.html", preview=preview, days=days, day_choices=DAY_CHOICES,
                               results=None, error=None, active_page="plan")

    @app.route("/plan/push", methods=["POST"])
    def plan_push_confirm():
        days = _days(request.form)
        db = app.config.get("DATABASE_PATH")
        selected = request.form.getlist("session")
        results, error = None, None
        if not selected:
            error = "Tick at least one workout to send."
        else:
            try:
                results = push_service.push(selected, request.form.get("token", ""), db_path=db, today=_today(), days=days)
            except push_service.PushError as err:
                error = str(err)
            except Exception as err:
                logger.warning("coros push failed: %s: %s", type(err).__name__, err)
                error = f"Sending failed ({type(err).__name__}). Check your COROS calendar before trying again."
        preview = push_service.build_preview(db_path=db, today=_today(), days=days)
        return render_template("push_preview.html", preview=preview, days=days, day_choices=DAY_CHOICES,
                               results=results, error=error, active_page="plan")
