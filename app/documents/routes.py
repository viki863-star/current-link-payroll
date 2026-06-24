import os, base64, logging
from datetime import date, datetime, timedelta
from pathlib import Path
from flask import render_template, request, redirect, url_for, flash, current_app, send_file, jsonify
from io import BytesIO
from . import documents_bp
from ..database import open_db
from app import csrf

logger = logging.getLogger(__name__)

ENTITY_LABELS = {
    "vehicle": "Vehicle",
    "employee": "Employee",
    "customer": "Customer",
    "supplier": "Supplier",
    "company": "Company",
}


def _expiry_status(expiry_date):
    if not expiry_date:
        return "ok"
    try:
        dt = datetime.strptime(expiry_date, "%Y-%m-%d").date()
        today = date.today()
        if dt < today:
            return "expired"
        if dt <= today + timedelta(days=30):
            return "soon"
        return "ok"
    except (ValueError, TypeError):
        return "ok"


@documents_bp.route("/documents")
def document_hub():
    db = open_db()
    q = request.args.get("q", "").strip()
    entity_type = request.args.get("entity_type", "").strip()
    expiry = request.args.get("expiry", "").strip()
    sort = request.args.get("sort", "uploaded_at")
    order = request.args.get("order", "desc")

    sql = "SELECT * FROM documents"
    where = []
    params = []
    if q:
        where.append("(doc_name LIKE ? OR doc_ref_no LIKE ? OR notes LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    if entity_type:
        where.append("entity_type = ?")
        params.append(entity_type)
    today_str = date.today().isoformat()
    if expiry == "expired":
        where.append("expiry_date IS NOT NULL AND expiry_date < ?")
        params.append(today_str)
    elif expiry == "soon":
        soon = (date.today() + timedelta(days=30)).isoformat()
        where.append("expiry_date IS NOT NULL AND expiry_date >= ? AND expiry_date <= ?")
        params.extend([today_str, soon])
    if where:
        sql += " WHERE " + " AND ".join(where)
    allowed_sort = {"doc_name", "doc_category", "entity_type", "expiry_date", "uploaded_at"}
    if sort not in allowed_sort:
        sort = "uploaded_at"
    sql += f" ORDER BY {sort} {'DESC' if order == 'desc' else 'ASC'}"
    docs = db.execute(sql, tuple(params)).fetchall()
    db.close()

    for d in docs:
        d["_status"] = _expiry_status(d.get("expiry_date"))

    return render_template("documents/hub.html", docs=docs, ENTITY_LABELS=ENTITY_LABELS,
        q=q, entity_type=entity_type, expiry=expiry, sort=sort, order=order, today=date.today())


@documents_bp.route("/documents/upload", methods=["GET", "POST"])
def document_upload():
    db = open_db()
    if request.method == "POST":
        entity_type = request.form.get("entity_type", "").strip()
        entity_id = request.form.get("entity_id", "").strip()
        doc_name = request.form.get("doc_name", "").strip()
        doc_category = request.form.get("doc_category", "Other").strip()
        doc_ref_no = request.form.get("doc_ref_no", "").strip() or None
        issue_date = request.form.get("issue_date", "").strip() or None
        expiry_date = request.form.get("expiry_date", "").strip() or None
        notes = request.form.get("notes", "").strip() or None
        file = request.files.get("file")

        if not entity_type or not entity_id or not doc_name or not file:
            flash("Entity, document name, and file are required.", "error")
            return render_template("documents/upload.html", ENTITY_LABELS=ENTITY_LABELS)

        file_data = base64.b64encode(file.read()).decode("utf-8")
        file_type = file.content_type or "application/octet-stream"
        file_size = len(file_data)

        db.execute(
            """INSERT INTO documents (entity_type, entity_id, doc_name, doc_category, doc_ref_no,
               issue_date, expiry_date, file_data, file_type, file_size, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (entity_type, entity_id, doc_name, doc_category, doc_ref_no,
             issue_date, expiry_date, file_data, file_type, file_size, notes),
        )
        db.commit()
        db.close()
        flash(f"Document '{doc_name}' uploaded.", "success")
        return redirect(url_for("documents.document_hub"))

    # GET: pre-fill entity from query params
    pre_type = request.args.get("entity_type", "")
    pre_id = request.args.get("entity_id", "")
    return render_template("documents/upload.html", ENTITY_LABELS=ENTITY_LABELS,
        pre_type=pre_type, pre_id=pre_id)


@documents_bp.route("/documents/<int:doc_id>/download")
def document_download(doc_id):
    db = open_db()
    doc = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    db.close()
    if not doc or not doc["file_data"]:
        flash("Document not found.", "error")
        return redirect(url_for("documents.document_hub"))
    data = base64.b64decode(doc["file_data"])
    ext = doc["file_type"].split("/")[-1] if "/" in doc["file_type"] else "bin"
    safe_name = f"{doc['doc_name']}.{ext}".replace("/", "-")
    return send_file(
        BytesIO(data),
        mimetype=doc["file_type"],
        as_attachment=True,
        download_name=safe_name,
    )


@documents_bp.route("/documents/<int:doc_id>/edit", methods=["GET", "POST"])
def document_edit(doc_id):
    db = open_db()
    doc = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not doc:
        db.close()
        flash("Document not found.", "error")
        return redirect(url_for("documents.document_hub"))

    if request.method == "POST":
        entity_type = request.form.get("entity_type", "").strip()
        entity_id = request.form.get("entity_id", "").strip()
        doc_name = request.form.get("doc_name", "").strip()
        doc_category = request.form.get("doc_category", "Other").strip()
        doc_ref_no = request.form.get("doc_ref_no", "").strip() or None
        issue_date = request.form.get("issue_date", "").strip() or None
        expiry_date = request.form.get("expiry_date", "").strip() or None
        notes = request.form.get("notes", "").strip() or None
        file = request.files.get("file")

        if not entity_type or not entity_id or not doc_name:
            flash("Entity and document name are required.", "error")
            return render_template("documents/upload.html", doc=doc, ENTITY_LABELS=ENTITY_LABELS)

        if file and file.filename:
            file_data = base64.b64encode(file.read()).decode("utf-8")
            file_type = file.content_type or "application/octet-stream"
            file_size = len(file_data)
            db.execute(
                """UPDATE documents SET entity_type=?, entity_id=?, doc_name=?, doc_category=?,
                   doc_ref_no=?, issue_date=?, expiry_date=?, notes=?, file_data=?, file_type=?, file_size=?
                   WHERE id=?""",
                (entity_type, entity_id, doc_name, doc_category, doc_ref_no,
                 issue_date, expiry_date, notes, file_data, file_type, file_size, doc_id),
            )
        else:
            db.execute(
                """UPDATE documents SET entity_type=?, entity_id=?, doc_name=?, doc_category=?,
                   doc_ref_no=?, issue_date=?, expiry_date=?, notes=?
                   WHERE id=?""",
                (entity_type, entity_id, doc_name, doc_category, doc_ref_no,
                 issue_date, expiry_date, notes, doc_id),
            )
        db.commit()
        db.close()
        flash(f"Document '{doc_name}' updated.", "success")
        return redirect(url_for("documents.document_hub"))

    db.close()
    return render_template("documents/upload.html", doc=doc, ENTITY_LABELS=ENTITY_LABELS)


@documents_bp.route("/documents/<int:doc_id>/delete", methods=["POST"])
def document_delete(doc_id):
    db = open_db()
    doc = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not doc:
        db.close()
        flash("Document not found.", "error")
        return redirect(url_for("documents.document_hub"))
    db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    db.commit()
    db.close()
    flash(f"Document '{doc['doc_name']}' deleted.", "success")
    return redirect(url_for("documents.document_hub"))


@documents_bp.route("/documents/search-entity")
def document_search_entity():
    entity_type = request.args.get("entity_type", "").strip()
    q = request.args.get("q", "").strip()
    db = open_db()
    results = []
    if entity_type == "vehicle":
        rows = db.execute(
            "SELECT plate_no AS id, plate_no || ' - ' || COALESCE(make_model,'') AS label FROM vehicles WHERE plate_no LIKE ? LIMIT 20",
            (f"%{q}%",)
        ).fetchall()
        results = [{"id": r["id"], "label": r["label"]} for r in rows]
    elif entity_type == "employee":
        rows = db.execute(
            "SELECT employee_id AS id, employee_id || ' - ' || COALESCE(full_name,'') AS label FROM employees WHERE employee_id LIKE ? OR full_name LIKE ? LIMIT 20",
            (f"%{q}%", f"%{q}%")
        ).fetchall()
        results = [{"id": r["id"], "label": r["label"]} for r in rows]
    elif entity_type == "customer":
        rows = db.execute(
            "SELECT id AS id, CAST(id AS TEXT) || ' - ' || COALESCE(customer_name,'') AS label FROM customers WHERE CAST(id AS TEXT) LIKE ? OR customer_name LIKE ? LIMIT 20",
            (f"%{q}%", f"%{q}%")
        ).fetchall()
        results = [{"id": r["id"], "label": r["label"]} for r in rows]
    elif entity_type == "supplier":
        rows = db.execute(
            "SELECT supplier_code AS id, supplier_code || ' - ' || COALESCE(supplier_name,'') AS label FROM suppliers WHERE supplier_code LIKE ? OR supplier_name LIKE ? LIMIT 20",
            (f"%{q}%", f"%{q}%")
        ).fetchall()
        results = [{"id": r["id"], "label": r["label"]} for r in rows]
    db.close()
    return jsonify(results)


@documents_bp.route("/documents/parse-pdf", methods=["POST"])
def document_parse_pdf():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty file"}), 400

    try:
        from pypdf import PdfReader
        from io import BytesIO
        import re

        pdf_bytes = f.read()
        reader = PdfReader(BytesIO(pdf_bytes))
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"

        text = text.strip()

        # If pypdf got no text, try OCR
        if not text:
            try:
                from pdf2image import convert_from_bytes
                import pytesseract
                images = convert_from_bytes(pdf_bytes, dpi=300)
                for img in images:
                    text += pytesseract.image_to_string(img) + "\n"
                text = text.strip()
            except ImportError as imp_err:
                text = text or f"[OCR packages not installed: {imp_err.name}]"
            except Exception as ocr_err:
                text = text or f"[OCR error: {ocr_err}]"

        # ─── Extract plate number ───
        plate_no = ""
        m = re.search(r"Traffic\s*Plate\s*No\.?\s*(\S+)", text, re.IGNORECASE)
        if m:
            plate_no = m.group(1).strip()
        if not plate_no:
            patterns = [
                r"(?:Plate\s*(?:No|#|Number)[:\s]*)([A-Z0-9\- ]{2,15})",
                r"(?:رقم اللوحة[:\s]*)([A-Z0-9\- ]{2,15})",
                r"(?:Registration\s*(?:No|#|Number)[:\s]*)([A-Z0-9\- ]{2,15})",
                r"(?:Vehicle\s*(?:No|#|Number)[:\s]*)([A-Z0-9\- ]{2,15})",
                r"(?:Plate)[:\s]*([A-Z0-9\- ]{2,15})",
                r"\b(\d{4,5})\b",
            ]
            for p in patterns:
                m = re.search(p, text, re.IGNORECASE)
                if m:
                    plate_no = m.group(1).strip()
                    break

        # ─── Extract expiry date ───
        expiry_date = ""
        m = re.search(r"Exp\.?\s*Date\s*(\d{2}[-\s][A-Z]{3}[-\s]\d{2,4})", text, re.IGNORECASE)
        if m:
            expiry_date = m.group(1).strip().replace(" ", "-")
        if not expiry_date:
            m = re.search(r"(?:Expir|Expiry|Expiration)[:\s]*([\d/\-]{8,12})", text, re.IGNORECASE)
            if m:
                expiry_date = m.group(1).strip()
        if not expiry_date:
            dates = re.findall(r"\b(\d{2}[/\-]\d{2}[/\-]\d{4})\b", text)
            dates += re.findall(r"\b(\d{4}[/\-]\d{2}[/\-]\d{2})\b", text)
            if len(dates) >= 1:
                expiry_date = dates[-1]

        # ─── Convert to YYYY-MM-DD ───
        def to_iso(d):
            mmm = re.match(r"(\d{2})[-\s]([A-Z]{3})[-\s](\d{2,4})", d, re.IGNORECASE)
            if mmm:
                months = {"JAN":"01","FEB":"02","MAR":"03","APR":"04","MAY":"05","JUN":"06",
                          "JUL":"07","AUG":"08","SEP":"09","OCT":"10","NOV":"11","DEC":"12"}
                day = mmm.group(1)
                mon = months.get(mmm.group(2).upper(), "01")
                yr = mmm.group(3)
                if len(yr) == 2:
                    yr = "20" + yr
                return f"{yr}-{mon}-{day}"
            m = re.match(r"(\d{2})[/\-](\d{2})[/\-](\d{4})", d)
            if m:
                return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
            m = re.match(r"(\d{4})[/\-](\d{2})[/\-](\d{2})", d)
            if m:
                return d.replace("/", "-")
            return d

        issue_date = ""
        expiry_date = to_iso(expiry_date) if expiry_date else ""

        # ─── Look up matching vehicle ───
        matched = False
        if plate_no:
            db = open_db()
            row = db.execute("SELECT plate_no, make_model FROM vehicles WHERE plate_no LIKE ?", (f"%{plate_no}%",)).fetchone()
            if row:
                plate_no = row["plate_no"]
                matched = True
            db.close()

        return jsonify({
            "plate_no": plate_no,
            "issue_date": issue_date,
            "expiry_date": expiry_date,
            "matched": matched,
            "text_preview": text[:500],
        })
    except Exception as e:
        return jsonify({"error": f"Failed to parse PDF: {str(e)}"}), 400

csrf.exempt(document_parse_pdf)
