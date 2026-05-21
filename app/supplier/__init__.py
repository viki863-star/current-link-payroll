from datetime import date, datetime

from flask import Blueprint

supplier_bp = Blueprint("supplier", __name__, template_folder="templates", url_prefix="/supplier")


@supplier_bp.context_processor
def inject_date():
    return {"date": date, "datetime": datetime}


from . import routes
