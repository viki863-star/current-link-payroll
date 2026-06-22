from flask import Blueprint, session, redirect, url_for, flash

core_bp = Blueprint("core", __name__, template_folder="templates")


@core_bp.before_request
def require_admin():
    role = session.get("role", "")
    if not role:
        flash("Please sign in first.", "error")
        return redirect(url_for("login"))
    if role != "admin" and role != "accounts":
        flash("You do not have access to that page.", "error")
        return redirect(url_for("login"))


from . import routes
