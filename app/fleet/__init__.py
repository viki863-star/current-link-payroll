from datetime import date, datetime

from flask import Blueprint, url_for

fleet_bp = Blueprint("fleet", __name__, template_folder="templates")


def _fmt_dt(value, fmt="%Y-%m-%d %H:%M"):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime(fmt)
    s = str(value).replace("T", " ").split(".")[0].strip()
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, f).strftime(fmt)
        except ValueError:
            continue
    return str(value)


@fleet_bp.context_processor
def inject_helpers():
    def vehicle_url(plate_no):
        return url_for("fleet.vehicle_profile", plate_no=plate_no)
    return {"date": date, "datetime": datetime, "vehicle_url": vehicle_url, "fmt_dt": _fmt_dt}


from . import routes
