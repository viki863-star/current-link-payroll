from datetime import date, datetime

from flask import Blueprint

fleet_bp = Blueprint("fleet", __name__, template_folder="templates")


@fleet_bp.context_processor
def inject_date():
    return {"date": date, "datetime": datetime}


from . import routes
