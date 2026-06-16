from datetime import date, datetime

from flask import Blueprint, session, redirect, url_for, flash

supplier_bp = Blueprint("supplier", __name__, template_folder="templates", url_prefix="/supplier")


@supplier_bp.before_request
def require_admin():
    role = session.get("role", "")
    if not role:
        flash("Please sign in first.", "error")
        return redirect(url_for("login"))
    if role != "admin" and role != "accounts":
        flash("You do not have access to that page.", "error")
        return redirect(url_for("login"))


@supplier_bp.context_processor
def inject_date():
    return {"date": date, "datetime": datetime}


from . import routes
