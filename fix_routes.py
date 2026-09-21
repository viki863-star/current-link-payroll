with open('app/documents/routes.py', 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# === LOCATION 1: document_upload (around line 227-254) ===
old1 = '''        thumbnail_data = None
        if doc_category == "Mulkiya":
            thumbnail_data = _generate_thumbnail(file_data, file_type)

        if existing:
            if thumbnail_data:
                db.execute(
                    """UPDATE documents SET doc_name=?, doc_ref_no=?, issue_date=?, expiry_date=?,
                       file_data=?, file_type=?, file_size=?, thumbnail_data=?, notes=?, uploaded_at=CURRENT_TIMESTAMP
                       WHERE id=?""",
                    (doc_name, doc_ref_no, issue_date, expiry_date, file_data, file_type, file_size, thumbnail_data, notes, existing["id"]),
                )
            else:
                db.execute(
                    """UPDATE documents SET doc_name=?, doc_ref_no=?, issue_date=?, expiry_date=?,
                       file_data=?, file_type=?, file_size=?, notes=?, uploaded_at=CURRENT_TIMESTAMP
                       WHERE id=?""",
                    (doc_name, doc_ref_no, issue_date, expiry_date, file_data, file_type, file_size, notes, existing["id"]),
                )
            msg = f"'{doc_name}' renewed (existing expired document updated)."
        else:
            if thumbnail_data:
                db.execute(
                    """INSERT INTO documents (entity_type, entity_id, doc_name, doc_category, doc_ref_no,
                       issue_date, expiry_date, file_data, file_type, file_size, thumbnail_data, notes)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (entity_type, entity_id, doc_name, doc_category, doc_ref_no,
                     issue_date, expiry_date, file_data, file_type, file_size, thumbnail_data, notes),
                )
            else:
                db.execute(
                    """INSERT INTO documents (entity_type, entity_id, doc_name, doc_category, doc_ref_no,
                       issue_date, expiry_date, file_data, file_type, file_size, notes)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (entity_type, entity_id, doc_name, doc_category, doc_ref_no,
                     issue_date, expiry_date, file_data, file_type, file_size, notes),
                )'''

new1 = '''        thumbnail_data = None
        thumbnail_back_data = None
        if doc_category == "Mulkiya":
            thumbnail_data, thumbnail_back_data = _generate_thumbnail(file_data, file_type)

        if existing:
            db.execute(
                """UPDATE documents SET doc_name=?, doc_ref_no=?, issue_date=?, expiry_date=?,
                   file_data=?, file_type=?, file_size=?, thumbnail_data=?, thumbnail_back_data=?, notes=?, uploaded_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (doc_name, doc_ref_no, issue_date, expiry_date, file_data, file_type, file_size, thumbnail_data, thumbnail_back_data, notes, existing["id"]),
            )
            msg = f"'{doc_name}' renewed (existing expired document updated)."
        else:
            db.execute(
                """INSERT INTO documents (entity_type, entity_id, doc_name, doc_category, doc_ref_no,
                   issue_date, expiry_date, file_data, file_type, file_size, thumbnail_data, thumbnail_back_data, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (entity_type, entity_id, doc_name, doc_category, doc_ref_no,
                 issue_date, expiry_date, file_data, file_type, file_size, thumbnail_data, thumbnail_back_data, notes),
            )'''

content = content.replace(old1, new1, 1)

# === LOCATION 2: bulk upload (around line 313-354) ===
old2 = '''            thumbnail_data = None
            if file and file.filename:
                file_data = base64.b64encode(file.read()).decode("utf-8")
                file_type = file.content_type or "application/octet-stream"
                file_size = len(file_data)
                if doc_category == "Mulkiya":
                    thumbnail_data = _generate_thumbnail(file_data, file_type)

            if existing:
                if file_data:
                    if thumbnail_data:
                        db.execute(
                            """UPDATE documents SET doc_name=?, doc_ref_no=?, expiry_date=?,
                               file_data=?, file_type=?, file_size=?, thumbnail_data=?, uploaded_at=CURRENT_TIMESTAMP
                               WHERE id=?""",
                            (doc_name, doc_ref_no, expiry_date, file_data, file_type, file_size, thumbnail_data, existing["id"]),
                        )
                    else:
                        db.execute(
                            """UPDATE documents SET doc_name=?, doc_ref_no=?, expiry_date=?,
                               file_data=?, file_type=?, file_size=?, uploaded_at=CURRENT_TIMESTAMP
                               WHERE id=?""",
                            (doc_name, doc_ref_no, expiry_date, file_data, file_type, file_size, existing["id"]),
                        )
                else:
                    db.execute(
                        """UPDATE documents SET doc_name=?, doc_ref_no=?, expiry_date=?,
                           uploaded_at=CURRENT_TIMESTAMP WHERE id=?""",
                        (doc_name, doc_ref_no, expiry_date, existing["id"]),
                    )
            else:
                if not file_data:
                    skipped.append(f"{entity_id} (no file attached)")
                    idx += 1
                    continue
                if thumbnail_data:
                    db.execute(
                        """INSERT INTO documents (entity_type, entity_id, doc_name, doc_category, doc_ref_no,
                           expiry_date, file_data, file_type, file_size, thumbnail_data)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (entity_type, entity_id, doc_name, doc_category, doc_ref_no,
                         expiry_date, file_data, file_type, file_size, thumbnail_data),
                    )
                else:
                    db.execute(
                        """INSERT INTO documents (entity_type, entity_id, doc_name, doc_category, doc_ref_no,
                           expiry_date, file_data, file_type, file_size)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (entity_type, entity_id, doc_name, doc_category, doc_ref_no,
                         expiry_date, file_data, file_type, file_size),
                    )'''

new2 = '''            thumbnail_data = None
            thumbnail_back_data = None
            if file and file.filename:
                file_data = base64.b64encode(file.read()).decode("utf-8")
                file_type = file.content_type or "application/octet-stream"
                file_size = len(file_data)
                if doc_category == "Mulkiya":
                    thumbnail_data, thumbnail_back_data = _generate_thumbnail(file_data, file_type)

            if existing:
                if file_data:
                    db.execute(
                        """UPDATE documents SET doc_name=?, doc_ref_no=?, expiry_date=?,
                           file_data=?, file_type=?, file_size=?, thumbnail_data=?, thumbnail_back_data=?, uploaded_at=CURRENT_TIMESTAMP
                           WHERE id=?""",
                        (doc_name, doc_ref_no, expiry_date, file_data, file_type, file_size, thumbnail_data, thumbnail_back_data, existing["id"]),
                    )
                else:
                    db.execute(
                        """UPDATE documents SET doc_name=?, doc_ref_no=?, expiry_date=?,
                           uploaded_at=CURRENT_TIMESTAMP WHERE id=?""",
                        (doc_name, doc_ref_no, expiry_date, existing["id"]),
                    )
            else:
                if not file_data:
                    skipped.append(f"{entity_id} (no file attached)")
                    idx += 1
                    continue
                db.execute(
                    """INSERT INTO documents (entity_type, entity_id, doc_name, doc_category, doc_ref_no,
                       expiry_date, file_data, file_type, file_size, thumbnail_data, thumbnail_back_data)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (entity_type, entity_id, doc_name, doc_category, doc_ref_no,
                     expiry_date, file_data, file_type, file_size, thumbnail_data, thumbnail_back_data),
                )'''

content = content.replace(old2, new2, 1)

# === LOCATION 3: document_edit (around line 466-484) ===
old3 = '''            thumbnail_data = None
            if doc_category == "Mulkiya":
                thumbnail_data = _generate_thumbnail(file_data, file_type)
            if thumbnail_data:
                db.execute(
                    """UPDATE documents SET entity_type=?, entity_id=?, doc_name=?, doc_category=?,
                       doc_ref_no=?, issue_date=?, expiry_date=?, notes=?, file_data=?, file_type=?, file_size=?, thumbnail_data=?
                       WHERE id=?""",
                    (entity_type, entity_id, doc_name, doc_category, doc_ref_no,
                     issue_date, expiry_date, notes, file_data, file_type, file_size, thumbnail_data, doc_id),
                )
            else:
                db.execute(
                    """UPDATE documents SET entity_type=?, entity_id=?, doc_name=?, doc_category=?,
                       doc_ref_no=?, issue_date=?, expiry_date=?, notes=?, file_data=?, file_type=?, file_size=?
                       WHERE id=?""",
                    (entity_type, entity_id, doc_name, doc_category, doc_ref_no,
                     issue_date, expiry_date, notes, file_data, file_type, file_size, doc_id),
                )'''

new3 = '''            thumbnail_data = None
            thumbnail_back_data = None
            if doc_category == "Mulkiya":
                thumbnail_data, thumbnail_back_data = _generate_thumbnail(file_data, file_type)
            db.execute(
                """UPDATE documents SET entity_type=?, entity_id=?, doc_name=?, doc_category=?,
                   doc_ref_no=?, issue_date=?, expiry_date=?, notes=?, file_data=?, file_type=?, file_size=?,
                   thumbnail_data=?, thumbnail_back_data=?
                   WHERE id=?""",
                (entity_type, entity_id, doc_name, doc_category, doc_ref_no,
                 issue_date, expiry_date, notes, file_data, file_type, file_size, thumbnail_data, thumbnail_back_data, doc_id),
            )'''

content = content.replace(old3, new3, 1)

with open('app/documents/routes.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Done!')
