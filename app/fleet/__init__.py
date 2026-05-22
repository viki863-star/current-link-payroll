from datetime import date, datetime
import urllib.parse

from flask import Blueprint, url_for

fleet_bp = Blueprint("fleet", __name__, template_folder="templates")


@fleet_bp.context_processor
def inject_helpers():
    def vehicle_url(plate_no):
        return url_for("fleet.vehicle_profile", plate_no=urllib.parse.quote(plate_no, safe=""))
    return {"date": date, "datetime": datetime, "vehicle_url": vehicle_url}


from . import routes
