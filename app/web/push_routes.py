"""Send planned runs to COROS. GET shows the preview (writes nothing); POST sends only what was confirmed.

Windows: one calendar month (default: this month) or the next 14 days. COROS accepts dates up to 90 days ahead,
so a season plan is sent a month at a time.
"""
import logging
from calendar import monthrange
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from flask import Flask, render_template, request

from app.coros_push import service as push_service

logger = logging.getLogger("coach.web.push")
DAY_CHOICES = (7, 14, 28, 35)


def month_windows(today: date) -> List[Dict[str, object]]:
    """Calendar months that overlap today .. today + 90 days."""
    out, cur = [], date(today.year, today.month, 1)
    limit = today + timedelta(days=push_service.MAX_AHEAD_DAYS)
    while cur <= limit:
        last = date(cur.year, cur.month, monthrange(cur.year, cur.month)[1])
        out.append({"key": f"{cur:%Y-%m}", "label": f"{cur:%B %Y}", "partial": last > limit or cur < today})
        cur = last + timedelta(days=1)
    return out


def _window(source, today: date) -> Tuple[Optional[str], int, Optional[date], Optional[date]]:
    month = source.get("month")
    if month:
        try:
            y, m = (int(x) for x in month.split("-"))
            return month, 14, date(y, m, 1), date(y, m, monthrange(y, m)[1])
        except (ValueError, TypeError):
            pass
    if source.get("days") is None:
        return (f"{today:%Y-%m}", 14, date(today.year, today.month, 1),
                date(today.year, today.month, monthrange(today.year, today.month)[1]))
    d = source.get("days", type=int) or 14
    return None, (d if d in DAY_CHOICES else 14), None, None


def register_push_routes(app: Flask) -> None:

    def _today_arg():
        return app.config.get("TODAY")       # test hook; None = real today

    def _render(preview, month, days, results=None, error=None):
        today = _today_arg() or date.today()
        return render_template("push_preview.html", preview=preview, days=days, month=month,
                               months=month_windows(today), day_choices=DAY_CHOICES,
                               results=results, error=error, active_page="plan")

    @app.route("/plan/push", methods=["GET"])
    def plan_push_preview():
        month, days, ws, we = _window(request.args, _today_arg() or date.today())
        preview = push_service.build_preview(db_path=app.config.get("DATABASE_PATH"), today=_today_arg(), days=days,
                                             window_start=ws, window_end=we)
        return _render(preview, month, days)

    @app.route("/plan/push", methods=["POST"])
    def plan_push_confirm():
        month, days, ws, we = _window(request.form, _today_arg() or date.today())
        db = app.config.get("DATABASE_PATH")
        selected = request.form.getlist("session")
        results, error = None, None
        if not selected:
            error = "Tick at least one workout to send."
        else:
            try:
                results = push_service.push(selected, request.form.get("token", ""), db_path=db, today=_today_arg(),
                                            days=days, window_start=ws, window_end=we)
            except push_service.PushError as err:
                error = str(err)
            except Exception as err:
                logger.warning("coros push failed: %s: %s", type(err).__name__, err)
                error = f"Sending failed ({type(err).__name__}). Check your COROS calendar before trying again."
        preview = push_service.build_preview(db_path=db, today=_today_arg(), days=days, window_start=ws, window_end=we)
        return _render(preview, month, days, results, error)
