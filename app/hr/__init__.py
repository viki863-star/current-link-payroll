from datetime import date, datetime

from flask import Blueprint

hr_bp = Blueprint("hr", __name__, template_folder="templates")


@hr_bp.context_processor
def inject_date():
    return {"date": date, "datetime": datetime}


from . import routes
