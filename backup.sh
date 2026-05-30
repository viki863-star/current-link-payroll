#!/usr/bin/env bash
set -e

# ─── CONFIG ────────────────────────────────────────
APP_DIR="/opt/current-link/app"
BACKUP_DIR="${APP_DIR}/backups"
DB_URL="${DATABASE_URL:-postgresql://user:pass@localhost:5432/currentlink}"
UPLOADS_DIR="${APP_DIR}/uploads"
RETENTION_DAYS=30
# ───────────────────────────────────────────────────

DATE=$(date +%Y-%m-%d)
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p "${BACKUP_DIR}/${DATE}"

echo "=== Backup started: ${TIMESTAMP} ==="

# 1. Database dump
echo "Dumping database..."
pg_dump "${DB_URL}" \
  --format=custom \
  --file="${BACKUP_DIR}/${DATE}/database_${TIMESTAMP}.dump"

# 2. Uploads folder
if [ -d "${UPLOADS_DIR}" ]; then
  echo "Archiving uploads..."
  tar -czf "${BACKUP_DIR}/${DATE}/uploads_${TIMESTAMP}.tar.gz" \
    -C "$(dirname "${UPLOADS_DIR}")" \
    "$(basename "${UPLOADS_DIR}")"
fi

# 3. Clean old backups
find "${BACKUP_DIR}" -type f -mtime +${RETENTION_DAYS} -delete
find "${BACKUP_DIR}" -type d -empty -delete 2>/dev/null || true

echo "=== Backup done: ${BACKUP_DIR}/${DATE} ==="
