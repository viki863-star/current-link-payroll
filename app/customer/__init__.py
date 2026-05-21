from datetime import date, datetime
from flask import Blueprint
import sqlite3

DB_PATH = r"D:\New project\payroll.db"

customer_bp = Blueprint("customer", __name__, template_folder="templates", url_prefix="/customer")

@customer_bp.context_processor
def inject_globals():
    try:
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        co = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
        db.close()
    except:
        co = None
    return {"date": date, "datetime": datetime, "company": co}

from . import routes
