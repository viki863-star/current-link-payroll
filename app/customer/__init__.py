from datetime import date, datetime
from flask import Blueprint, current_app
import sqlite3
import os

customer_bp = Blueprint("customer", __name__, template_folder="templates", url_prefix="/customer")

@customer_bp.context_processor
def inject_globals():
    try:
        db_path = current_app.config.get("DATABASE") or os.path.join(current_app.root_path, "..", "payroll.db")
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        co = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
        db.close()
    except:
        co = None
    return {"date": date, "datetime": datetime, "company": co}

from . import routes
