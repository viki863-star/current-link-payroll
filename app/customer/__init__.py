from datetime import date, datetime
from flask import Blueprint, current_app, session, redirect, url_for, flash
import sqlite3
import os

customer_bp = Blueprint("customer", __name__, template_folder="templates", url_prefix="/customer")

@customer_bp.before_request
def require_admin():
    role = session.get("role", "")
    if not role:
        flash("Please sign in first.", "error")
        return redirect(url_for("login"))
    if role != "admin" and role != "accounts":
        flash("You do not have access to that page.", "error")
        return redirect(url_for("login"))

@customer_bp.context_processor
def inject_globals():
    try:
        db_path = current_app.config.get("DATABASE") or os.path.join(current_app.root_path, "..", "payroll.db")
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        db.executescript("CREATE TABLE IF NOT EXISTS company_profile (id INTEGER PRIMARY KEY AUTOINCREMENT, company_name TEXT)")
        co = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
        db.close()
    except:
        co = None

    def amount_in_words(n):
        if n == 0: return "Zero"
        o = ["","One","Two","Three","Four","Five","Six","Seven","Eight","Nine","Ten","Eleven","Twelve",
             "Thirteen","Fourteen","Fifteen","Sixteen","Seventeen","Eighteen","Nineteen"]
        t = ["","","Twenty","Thirty","Forty","Fifty","Sixty","Seventy","Eighty","Ninety"]
        sc = ["","Thousand","Million","Billion"]
        def h(num):
            r = ""
            if num >= 100: r += o[num//100] + " Hundred"; num %= 100
            if num and r: r += " "
            if num >= 20: r += t[num//10]; num %= 10
            if num and r: r += " "
            if num > 0: r += o[num]
            return r.strip()
        ip = int(n)
        dp = min(int(round((n - ip) * 100)), 99)
        if ip == 0: w = "Zero"
        else:
            w = ""; i = 0
            while ip > 0:
                ck = ip % 1000
                if ck:
                    cw = h(ck)
                    if sc[i]: cw += " " + sc[i]
                    w = cw + (" " + w if w else "")
                ip //= 1000; i += 1
        if dp: w += f" and {dp:02d}/100"
        return "AED " + w + " Only"

    return {"date": date, "datetime": datetime, "company": co, "amount_in_words": amount_in_words}

from . import routes
