import sys
sys.path.insert(0, "/opt/current-link/app")
from app import create_app
from app.database import open_db
from app.documents.routes import _generate_thumbnail

app = create_app()
with app.app_context():
    db = open_db()
    rows = db.execute("SELECT id, file_data, file_type FROM documents WHERE entity_type = 'vehicle' AND doc_category = 'Mulkiya' AND (thumbnail_data IS NULL OR thumbnail_data = '')").fetchall()
    print(f"Found {len(rows)} Mulkiya docs without thumbnail")
    for row in rows:
        doc_id = row["id"]
        file_data = row["file_data"]
        file_type = row["file_type"]
        if not file_data:
            print(f"  ID {doc_id}: no file_data, skipping")
            continue
        try:
            thumb, preview = _generate_thumbnail(file_data, file_type)
            if thumb:
                db.execute("UPDATE documents SET thumbnail_data = %s, pdf_preview_data = %s WHERE id = %s", (thumb, preview, doc_id))
                print(f"  ID {doc_id}: generated thumbnail ({len(thumb)} bytes)")
            else:
                print(f"  ID {doc_id}: thumbnail generation returned None")
        except Exception as e:
            print(f"  ID {doc_id}: error - {e}")
    db.commit()
    print("Done!")
