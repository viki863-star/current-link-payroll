import os, base64, logging, zipfile
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
    cat = request.args.get("cat", "").strip()
    sort = request.args.get("sort", "uploaded_at")
    order = request.args.get("order", "desc")

    sql = "SELECT id, entity_type, entity_id, doc_name, doc_category, doc_ref_no, issue_date, expiry_date, file_type, file_size, notes, uploaded_at FROM documents"
    where = []
    params = []
    if q:
        where.append("(doc_name LIKE ? OR doc_ref_no LIKE ? OR entity_id LIKE ? OR notes LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"])
    if entity_type:
        where.append("entity_type = ?")
        params.append(entity_type)
    if cat:
        where.append("doc_category = ?")
        params.append(cat)
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
        ua = d.get("uploaded_at")
        if isinstance(ua, datetime):
            d["uploaded_at_formatted"] = ua.strftime("%Y-%m-%d")
        elif ua:
            d["uploaded_at_formatted"] = str(ua)[:10]
        else:
            d["uploaded_at_formatted"] = ""

    return render_template("documents/hub.html", docs=docs, ENTITY_LABELS=ENTITY_LABELS,
        q=q, entity_type=entity_type, expiry=expiry, cat=cat, sort=sort, order=order, today=date.today())


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

        existing = db.execute(
            "SELECT id, expiry_date FROM documents WHERE entity_type=? AND entity_id=? AND doc_category=? ORDER BY uploaded_at DESC LIMIT 1",
            (entity_type, entity_id, doc_category)
        ).fetchone()

        if existing and _expiry_status(existing["expiry_date"]) != "expired":
            db.close()
            flash(f"A valid '{doc_category}' already exists for this {entity_type}. It must expire before you can upload a new one.", "error")
            return redirect(url_for("documents.document_hub"))

        file_data = base64.b64encode(file.read()).decode("utf-8")
        file_type = file.content_type or "application/octet-stream"
        file_size = len(file_data)

        if existing:
            db.execute(
                """UPDATE documents SET doc_name=?, doc_ref_no=?, issue_date=?, expiry_date=?,
                   file_data=?, file_type=?, file_size=?, notes=?, uploaded_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (doc_name, doc_ref_no, issue_date, expiry_date, file_data, file_type, file_size, notes, existing["id"]),
            )
            msg = f"'{doc_name}' renewed (existing expired document updated)."
        else:
            db.execute(
                """INSERT INTO documents (entity_type, entity_id, doc_name, doc_category, doc_ref_no,
                   issue_date, expiry_date, file_data, file_type, file_size, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (entity_type, entity_id, doc_name, doc_category, doc_ref_no,
                 issue_date, expiry_date, file_data, file_type, file_size, notes),
            )
            msg = f"Document '{doc_name}' uploaded."

        db.commit()
        db.close()
        flash(msg, "success")
        return redirect(url_for("documents.document_hub"))

    # GET: pre-fill entity from query params
    pre_type = request.args.get("entity_type", "")
    pre_id = request.args.get("entity_id", "")
    return render_template("documents/upload.html", ENTITY_LABELS=ENTITY_LABELS,
        pre_type=pre_type, pre_id=pre_id)


@documents_bp.route("/documents/bulk", methods=["GET", "POST"])
def document_bulk():
    db = open_db()
    if request.method == "POST":
        doc_category = request.form.get("doc_category", "Mulkiya").strip()
        uploaded = 0
        idx = 0
        while True:
            entity_type = request.form.get(f"entity_type_{idx}")
            if entity_type is None:
                break
            entity_id = request.form.get(f"entity_id_{idx}", "").strip()
            expiry_date = request.form.get(f"expiry_date_{idx}", "").strip() or None
            doc_ref_no = request.form.get(f"doc_ref_no_{idx}", "").strip() or None
            if not entity_id:
                idx += 1
                continue
            doc_name = request.form.get(f"doc_name_{idx}", "").strip()
            if not doc_name:
                doc_name = f"{doc_category} {idx+1}"
            existing = db.execute(
                "SELECT id, expiry_date FROM documents WHERE entity_type=? AND entity_id=? AND doc_category=? ORDER BY uploaded_at DESC LIMIT 1",
                (entity_type, entity_id, doc_category)
            ).fetchone()

            if existing and _expiry_status(existing["expiry_date"]) != "expired":
                idx += 1
                continue

            file = request.files.get(f"file_{idx}")
            file_data = None
            file_type = None
            file_size = 0
            if file and file.filename:
                file_data = base64.b64encode(file.read()).decode("utf-8")
                file_type = file.content_type or "application/octet-stream"
                file_size = len(file_data)

            if existing:
                db.execute(
                    """UPDATE documents SET doc_name=?, doc_ref_no=?, expiry_date=?,
                       file_data=?, file_type=?, file_size=?, uploaded_at=CURRENT_TIMESTAMP
                       WHERE id=?""",
                    (doc_name, doc_ref_no, expiry_date, file_data, file_type, file_size, existing["id"]),
                )
            else:
                db.execute(
                    """INSERT INTO documents (entity_type, entity_id, doc_name, doc_category, doc_ref_no,
                       expiry_date, file_data, file_type, file_size)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (entity_type, entity_id, doc_name, doc_category, doc_ref_no,
                     expiry_date, file_data, file_type, file_size),
                )
            uploaded += 1
            idx += 1
        db.commit()
        db.close()
        if uploaded:
            flash(f"{uploaded} document(s) uploaded successfully.", "success")
        else:
            flash("No valid entries to upload.", "error")
        return redirect(url_for("documents.document_hub"))

    return render_template("documents/bulk.html", ENTITY_LABELS=ENTITY_LABELS)


@documents_bp.route("/documents/<int:doc_id>/download")
def document_download(doc_id):
    db = open_db()
    doc = db.execute("SELECT id, entity_type, entity_id, doc_name, doc_category, issue_date, expiry_date, file_name, file_type, file_data, created_at FROM documents WHERE id=?", (doc_id,)).fetchone()
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


@documents_bp.route("/documents/download-expired")
def document_download_expired():
    db = open_db()
    today_str = date.today().isoformat()
    docs = db.execute(
        "SELECT id, entity_type, entity_id, doc_name, doc_category, issue_date, expiry_date, file_name, file_type, file_data FROM documents WHERE expiry_date IS NOT NULL AND expiry_date < ? ORDER BY entity_type, entity_id",
        (today_str,)
    ).fetchall()
    db.close()

    if not docs:
        flash("No expired documents to download.", "error")
        return redirect(url_for("documents.document_hub"))

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for d in docs:
            if not d["file_data"]:
                continue
            data = base64.b64decode(d["file_data"])
            ext = d["file_type"].split("/")[-1] if "/" in d["file_type"] else "bin"
            safe_name = f"{d['entity_id']}_{d['doc_name']}.{ext}".replace("/", "-").replace(" ", "_")
            zf.writestr(safe_name, data)

    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"expired_documents_{date.today().isoformat()}.zip",
    )


@documents_bp.route("/documents/<int:doc_id>/edit", methods=["GET", "POST"])
def document_edit(doc_id):
    db = open_db()
    doc = db.execute("SELECT id, entity_type, entity_id, doc_name, doc_category, issue_date, expiry_date, file_name, file_type, created_at FROM documents WHERE id=?", (doc_id,)).fetchone()
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
    doc = db.execute("SELECT id, entity_type, entity_id, doc_name, doc_category, issue_date, expiry_date, file_name, file_type, created_at FROM documents WHERE id=?", (doc_id,)).fetchone()
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
    check_cat = request.args.get("check_category", "").strip()
    db = open_db()

    today_str = date.today().isoformat()
    results = []

    base_queries = {
        "vehicle": (
            "SELECT plate_no AS id, plate_no || ' - ' || COALESCE(model,'') AS label FROM vehicles WHERE plate_no LIKE ? OR model LIKE ?",
            [f"%{q}%", f"%{q}%"]
        ),
        "employee": (
            "SELECT employee_id AS id, employee_id || ' - ' || COALESCE(full_name,'') AS label FROM employees WHERE employee_id LIKE ? OR full_name LIKE ?",
            [f"%{q}%", f"%{q}%"]
        ),
        "customer": (
            "SELECT id AS id, CAST(id AS TEXT) || ' - ' || COALESCE(customer_name,'') AS label FROM customers WHERE CAST(id AS TEXT) LIKE ? OR customer_name LIKE ?",
            [f"%{q}%", f"%{q}%"]
        ),
        "supplier": (
            "SELECT supplier_code AS id, supplier_code || ' - ' || COALESCE(supplier_name,'') AS label FROM suppliers WHERE supplier_code LIKE ? OR supplier_name LIKE ?",
            [f"%{q}%", f"%{q}%"]
        ),
    }

    if entity_type in base_queries:
        sql, params = base_queries[entity_type]
        rows = db.execute(sql + " LIMIT 20", params).fetchall()

        if check_cat:
            valid_ids = set(
                r["entity_id"] for r in db.execute(
                    "SELECT entity_id FROM documents WHERE entity_type=? AND doc_category=? AND (expiry_date IS NULL OR expiry_date >= ?)",
                    (entity_type, check_cat, today_str)
                ).fetchall()
            )
        else:
            valid_ids = set()

        results = []
        for r in rows:
            has_valid = r["id"] in valid_ids
            results.append({"id": r["id"], "label": r["label"], "has_valid": has_valid})

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
                pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"
                images = convert_from_bytes(pdf_bytes, dpi=400, poppler_path="/usr/bin")
                for img in images:
                    # Preprocess: grayscale → high contrast → enlarge
                    gray = img.convert('L')
                    bw = gray.point(lambda x: 0 if x < 160 else 255)
                    big = bw.resize((bw.width * 2, bw.height * 2), 0)
                    text += pytesseract.image_to_string(big, lang="eng+ara", config="--psm 4 --oem 3") + "\n"
                text = text.strip()
            except ImportError as imp_err:
                text = text or f"[OCR packages not installed: {imp_err.name}]"
            except Exception as ocr_err:
                text = text or f"[OCR error: {ocr_err}]"

        # ─── STEP 1: OCR Cleanup ───
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            # Remove very short noise lines
            if len(line) < 2:
                continue
            cleaned_lines.append(line)
        cleaned = '\n'.join(cleaned_lines)

        # ─── STEP 2: Extract ───
        plate_no = ""

        # Look for "Traffic Plate No." label (may be split across lines)
        for i, line in enumerate(cleaned_lines):
            if re.search(r'Traffic.*Plate|Plate.*No\.?|رقم اللوحة', line, re.IGNORECASE):
                # The value might be on the same line or next line
                val = re.sub(r'^.*?(?:Traffic.*?Plate.*?No\.?\s*|رقم اللوحة[:\s]*)', '', line, flags=re.IGNORECASE).strip()
                if not val and i + 1 < len(cleaned_lines):
                    val = cleaned_lines[i + 1]
                if val:
                    # Take only until next field label or end of line
                    val = re.split(r'\s{3,}|Exp\.?\s*Date|انتهاء', val)[0].strip()
                    val = re.sub(r'\s*/\s*', '/', val)  # "1 / 80900" → "1/80900"
                    plate_no = val
                break

        expiry_date = ""
        for i, line in enumerate(cleaned_lines):
            if re.search(r'Exp\.?\s*Date|انتهاء الترخيص', line, re.IGNORECASE):
                val = re.sub(r'^.*?(?:Exp\.?\s*Date[:\s]*|انتهاء الترخيص[:\s]*)', '', line, flags=re.IGNORECASE).strip()
                if not val and i + 1 < len(cleaned_lines):
                    val = cleaned_lines[i + 1]
                if val:
                    val = val.split()[0] if val.split() else val
                    expiry_date = val
                break

        # ─── Convert to YYYY-MM-DD ───
        def to_iso(d):
            mmm = re.match(r"(\d{2})[-\s]([A-Za-z]{3})[-\s](\d{2,4})", d.strip(), re.IGNORECASE)
            if mmm:
                months = {"JAN":"01","FEB":"02","MAR":"03","APR":"04","MAY":"05","JUN":"06",
                          "JUL":"07","AUG":"08","SEP":"09","OCT":"10","NOV":"11","DEC":"12"}
                day = mmm.group(1)
                mon = months.get(mmm.group(2).upper(), "01")
                yr = mmm.group(3)
                if len(yr) == 2:
                    yr = "20" + yr
                return f"{yr}-{mon}-{day}"
            return d

        issue_date = ""
        expiry_date = to_iso(expiry_date) if expiry_date else ""

        # ─── Look up matching vehicle ───
        matched = False
        if plate_no:
            db = open_db()
            row = db.execute("SELECT plate_no FROM vehicles WHERE plate_no LIKE ?", (f"%{plate_no}%",)).fetchone()
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
