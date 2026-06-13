import os, base64, logging
from datetime import datetime
from pathlib import Path
from flask import render_template, request, redirect, url_for, flash, current_app, send_file
from . import core_bp
from ..database import open_db

logger = logging.getLogger(__name__)


@core_bp.route("/settings", methods=["GET", "POST"])
def settings():
    try:
        db = open_db()
        company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
        if request.method == "POST":
            action = request.form.get("action", "")
            if action == "save_company":
                name = request.form.get("company_name", "").strip()
                if company:
                    db.execute("""UPDATE company_profile SET company_name=?,legal_name=?,trade_license_no=?,trade_license_expiry=?,
                        trn_no=?,vat_status=?,phone_number=?,email=?,address=?,bank_name=?,bank_account_name=?,
                        bank_account_number=?,iban=?,swift_code=?,invoice_terms=?,base_currency=?,
                        financial_year_label=?,financial_year_start=?,financial_year_end=? WHERE id=?""",
                        (name, request.form.get("legal_name"), request.form.get("trade_license_no"),
                         request.form.get("trade_license_expiry"), request.form.get("trn_no"),
                         request.form.get("vat_status", "Registered"), request.form.get("phone_number"),
                         request.form.get("email"), request.form.get("address"), request.form.get("bank_name"),
                         request.form.get("bank_account_name"), request.form.get("bank_account_number"),
                         request.form.get("iban"), request.form.get("swift_code"),
                         request.form.get("invoice_terms"), request.form.get("base_currency", "AED"),
                         request.form.get("financial_year_label"), request.form.get("financial_year_start"),
                         request.form.get("financial_year_end"), company["id"]))
                else:
                    db.execute("""INSERT INTO company_profile (company_name,legal_name,trade_license_no,trade_license_expiry,
                        trn_no,vat_status,phone_number,email,address,bank_name,bank_account_name,
                        bank_account_number,iban,swift_code,invoice_terms,base_currency,
                        financial_year_label,financial_year_start,financial_year_end)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (name, request.form.get("legal_name"), request.form.get("trade_license_no"),
                         request.form.get("trade_license_expiry"), request.form.get("trn_no"),
                         request.form.get("vat_status", "Registered"), request.form.get("phone_number"),
                         request.form.get("email"), request.form.get("address"), request.form.get("bank_name"),
                         request.form.get("bank_account_name"), request.form.get("bank_account_number"),
                         request.form.get("iban"), request.form.get("swift_code"),
                         request.form.get("invoice_terms"), request.form.get("base_currency", "AED"),
                         request.form.get("financial_year_label"), request.form.get("financial_year_start"),
                         request.form.get("financial_year_end")))
                db.commit()
                flash("Company details saved.", "success")
            elif action == "save_bank":
                if company:
                    db.execute("""UPDATE company_profile SET bank_name=?,bank_account_name=?,bank_account_number=?,iban=?,swift_code=? WHERE id=?""",
                        (request.form.get("bank_name"), request.form.get("bank_account_name"),
                         request.form.get("bank_account_number"), request.form.get("iban"),
                         request.form.get("swift_code"), company["id"]))
                else:
                    db.execute("""INSERT INTO company_profile (company_name,bank_name,bank_account_name,bank_account_number,iban,swift_code)
                        VALUES ('My Company',?,?,?,?,?)""",
                        (request.form.get("bank_name"), request.form.get("bank_account_name"),
                         request.form.get("bank_account_number"), request.form.get("iban"),
                         request.form.get("swift_code")))
                db.commit()
                flash("Bank details saved.", "success")
            elif action == "save_logo":
                file = request.files.get("logo_file")
                if file and file.filename:
                    logo_data = base64.b64encode(file.read()).decode("utf-8")
                    logo_type = file.content_type
                    if company:
                        db.execute("UPDATE company_profile SET logo_data=?,logo_type=? WHERE id=?", (logo_data, logo_type, company["id"]))
                    else:
                        db.execute("INSERT INTO company_profile (company_name,logo_data,logo_type) VALUES ('My Company',?,?)", (logo_data, logo_type))
                    db.commit()
                    flash("Logo updated.", "success")
            elif action == "remove_logo":
                if company:
                    db.execute("UPDATE company_profile SET logo_data=NULL,logo_type=NULL WHERE id=?", (company["id"],))
                    db.commit()
                    flash("Logo removed.", "success")
            elif action == "save_theme":
                theme_color = request.form.get("theme_color", "#0F2B52").strip()
                if company:
                    db.execute("UPDATE company_profile SET theme_color=? WHERE id=?", (theme_color, company["id"]))
                else:
                    db.execute("INSERT INTO company_profile (company_name,theme_color) VALUES ('My Company',?)", (theme_color,))
                db.commit()
                flash("Theme updated.", "success")
            db.close()
            return redirect(url_for("core.settings"))
        company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
        db.close()
        return render_template("settings.html", company=company)
    except Exception as e:
        logger.exception("Settings page error")
        flash(f"Error loading settings: {e}", "error")
        return redirect(url_for("dashboard"))


@core_bp.route("/settings/download-db-backup")
def download_db_backup():
    db = open_db()
    company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
    db.close()
    backup_dir = Path(current_app.config.get("GENERATED_DIR", "generated")) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"db_backup_{ts}.sql"
    try:
        import subprocess
        pg_dump = os.environ.get("PG_DUMP_PATH", "pg_dump")
        db_url = current_app.config.get("DATABASE_URL", "")
        if db_url:
            subprocess.run([pg_dump, db_url, "-f", str(backup_path)], check=True)
        else:
            raise RuntimeError("No DATABASE_URL configured")
        return send_file(str(backup_path), as_attachment=True, download_name=f"currentlink_backup_{ts}.sql")
    except Exception as e:
        flash(f"Backup failed: {e}", "error")
        return redirect(url_for("core.settings"))
