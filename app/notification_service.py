from __future__ import annotations

from datetime import datetime
from flask import current_app
from .database import open_db

NOTIF_TABLE = """
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL DEFAULT 'admin',
    type TEXT NOT NULL DEFAULT 'info',
    title TEXT NOT NULL,
    message TEXT,
    link TEXT,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
)
"""


def _ensure_table():
    db = open_db()
    db.execute(NOTIF_TABLE)
    db.commit()
    db.close()


def add_notification(title: str, type: str = "info", role: str = "admin", message: str = None, link: str = None):
    _ensure_table()
    db = open_db()
    db.execute(
        "INSERT INTO notifications (role, type, title, message, link, is_read, created_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
        (role, type, title, message, link, datetime.now().isoformat()),
    )
    db.commit()
    db.close()


def get_unread_notifications(role: str = "admin", limit: int = 20):
    _ensure_table()
    db = open_db()
    rows = db.execute(
        "SELECT id, type, title, message, link, is_read, created_at FROM notifications WHERE role=? ORDER BY created_at DESC LIMIT ?",
        (role, limit),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def unread_count(role: str = "admin"):
    _ensure_table()
    db = open_db()
    count = db.execute(
        "SELECT COUNT(*) FROM notifications WHERE role=? AND is_read=0", (role,)
    ).fetchone()[0]
    db.close()
    return count


def mark_as_read(notif_id: int):
    db = open_db()
    db.execute("UPDATE notifications SET is_read=1 WHERE id=?", (notif_id,))
    db.commit()
    db.close()


def mark_all_read(role: str = "admin"):
    db = open_db()
    db.execute("UPDATE notifications SET is_read=1 WHERE role=? AND is_read=0", (role,))
    db.commit()
    db.close()
