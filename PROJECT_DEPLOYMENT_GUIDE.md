# Current Link Payroll — Project & Deployment Guide

This document gives a complete picture of the project (local PC, GitHub, production
server, database, backups) so that ANY engineer/AI agent can safely understand the
system and deploy changes without breaking anything.

> ⚠️ SECURITY: This repo is **private** business software. The files
> `deploy_helper.py` and `ssh_run.py` contain real server login credentials.
> NEVER push this repository to a public remote, never commit `.env`, and never
> print passwords/logs into chat messages unnecessarily.

---

## 1. What this project is

A multi-user ERP/accounting web app ("Current Link") for a UAE transport &
contracting company. It manages:

- **Drivers / Employees / HR** — employee records, join dates, salary storage
  (`salary_store`), salary slips, perata, Employee Statement (Kata) PDFs.
- **Driver finance** — advances/transactions, salary runs, owner-fund source links.
- **Suppliers** — invoices, expense/earnings, LPO, quotations, payments, loans, Kata.
- **Customers** — invoices (normal & NMDC), LPOs, quotations, statements.
- **Fleet** — vehicles, staff advances, fuel, fuel-bulk entry.
- **Accounts** — owner fund, cash reports, tax, audit logs.
- **AI assistant** — built-in chat blueprint.
- **Documents** — uploads/attachments.

Tech stack: **Python 3 (Flask) + PostgreSQL (production) / SQLite (local dev),
Waitress (app server), Nginx (reverse proxy + TLS), ReportLab (PDFs)**.

---

## 2. Local development PC (this machine)

| Item | Value |
|---|---|
| Working directory | `C:\Users\user\current-link-payroll` |
| Local Python | 3.14.4 (Windows) |
| App entrypoint | `serve.py` → `app.create_app()` → Waitress on port `7860` |
| Local DB (default) | SQLite `D:/CurrentLinkData/Database/payroll.db` |
| Local generated files | `D:/CurrentLinkData/Generated` |
| Local backups | `D:/CurrentLinkData/Backups` |
| Config file | `.env` (git-ignored) — see `app/__init__.py` for all keys |
| Pip deps | `requirements.txt` (Flask, Waitress, `psycopg[binary]`, ReportLab, pypdf, arabic-reshaper, python-bidi, ...) |

### 2.1 Key files in the repo root

| File | Purpose |
|---|---|
| `serve.py` | Waitress entrypoint on `0.0.0.0:7860` |
| `app/__init__.py` | Flask factory; loads `.env`, storage layout, blueprints, DB init |
| `app/database.py` | `SQLITE_SCHEMA`, `POSTGRES_SCHEMA`, `DatabaseAdapter`, `init_db` (110 tables) |
| `app/routes.py` | Main blueprint routes (large: ~19k+ lines) |
| `app/pdf_service.py` | All PDF generators (kata, slips, invoices, LPO, etc.) |
| `app/hr/routes.py` | HR + employee salary/JSON/kata routes (blueprint `hr`) |
| `app/supplier/routes.py` | Supplier routes (blueprint `supplier`) |
| `app/customer/routes.py` | Customer routes (blueprint `customer`) |
| `app/fleet/routes.py` | Fleet routes (blueprint `fleet`) |
| `app/backup_service.py` | In-app daily/weekly/monthly DB backups |
| `deploy_helper.py` | One-shot deploy script (backup → git reset → restart) **has creds** |
| `ssh_run.py` | Runs a shell command on the server over paramiko **has creds** |
| `requirements.txt` | Python dependencies |
| `.env` (ignored) | Local environment config | 

### 2.2 Git configuration

- Remotes:
  - `origin` → `https://github.com/viki863-star/current-link-payroll.git`
  - `payroll` → same URL (alias)
- Branch: `main`
- Git identity: `admin <admin@currentlinkgc.com>` (only relevant for commits)

---

## 3. GitHub repository

- **URL**: `https://github.com/viki863-star/current-link-payroll`
- **Owner**: `viki863-star`
- **Branch**: `main` (single working branch)
- **Push method**: HTTPS over PowerShell git; creds stored via Windows Credential
  Manager (`credential.helper = manager`).
- Commit history note: there are `.py` helper scripts in the root from past fixes
  (e.g. `fix_*.py`, `check_*.py`) — these are dev artifacts, not part of the app.

---

## 4. Production server

| Item | Value |
|---|---|
| Host | `207.180.245.64` |
| SSH | port `22`, user `root` (see `ssh_run.py` / `deploy_helper.py` for password) |
| App directory | `/opt/current-link/app` (a git clone of `main`) |
| Virtualenv | `/opt/current-link/app/.venv` (Python 3.12.3) |
| App server | Waitress on `0.0.0.0:7860` (threads=3) |
| Systemd unit | `current-link.service` (ExecStart `serve.py`) |
| Reverse proxy | Nginx → `http://127.0.0.1:7860` (sites-enabled `current-link`) |
| Domain | `https://www.currentlinkgc.com` (also `currentlinkgc.com`, IP) |
| TLS | Let's Encrypt / Certbot (auto-renew) |
| Database | PostgreSQL 16.14, DB name `currentlink_payroll` (via `DATABASE_URL`) |
| Data files | `/opt/current-link/data/generated`, `/opt/current-link/data/Backups` |
| Code backups | `/opt/current-link/app_backup_YYYY-MM-DD_HHMM` (keeps last 5) |

### 4.1 systemd unit (current-link.service)

```
[Service]
User=root
WorkingDirectory=/opt/current-link/app
Environment="PATH=/opt/current-link/app/.venv/bin"
ExecStart=/opt/current-link/app/.venv/bin/python /opt/current-link/app/serve.py
Restart=always
RestartSec=5
```

### 4.2 Nginx (sites-enabled/current-link)

- `proxy_pass http://127.0.0.1:7860;`
- SSL on 443 (Let's Encrypt), 80 redirects to HTTPS.
- `client_max_body_size 50M` (for uploads).

### 4.3 Database backend switch

`app/database.py:init_db()`:
- If `DATABASE_URL` is set → **PostgreSQL** backend.
- Else → **SQLite** from `DATABASE` path.
- Production `.env` sets `DATABASE_URL` (PostgreSQL) + `REQUIRE_DATABASE_URL`.
- Local `.env` uses SQLite (`DATABASE_FILE=D:/CurrentLinkData/Database/payroll.db`).

`app/__init__.py` also runs a **daily backup thread** on startup
(`ensure_daily_backup_for_today`), plus `backup_service.py` has
`cleanup_old_backups` (single rolling backup per type).

---

## 5. Backups & data safety

Layers of protection, in order:

1. **Code backups (per deploy)** — `deploy_helper.py` copies the whole `app` folder
   to `/opt/current-link/app_backup_<date>_<time>` before updating; only last 5 kept.
   Rollback = point Nginx/unit back or `git checkout` from the backup dir.
2. **Cron DB backup** — nightly `0 2 * * *` runs `/opt/current-link/app/backup.sh`,
   which `pg_dump`s `$DATABASE_URL` to `/opt/current-link/app/backups/<date>/`.
   (NOTE: currently the cron has "Permission denied" because `backup.sh` is not
   executable — `chmod +x backup.sh` on the server to fix.)
3. **In-app backup thread** — daily/weekly/monthly rolling backups written under
   `GENERATED_BACKUP_DIR` (`/opt/current-link/data/Backups`).
4. **Local PC** — SQLite `payroll.db` + generated files under `D:/CurrentLinkData`;
   mirroring hooks exist (`PC_MIRROR_*` env keys) but are optional.

> ⚠️ **Data safety rule for agents**: NEVER run raw SQL or restart the DB from a
> guess. Prefer `deploy_helper.py` for deploys, which always backs up first.
> If you must edit data, take an explicit backup first.

---

## 6. HOW TO DEPLOY A CHANGE (safe, standard flow)

Required: SSH access creds (in `deploy_helper.py` / `ssh_run.py`), push rights to `main`.

**Step 1 — Edit code locally**
Work in `C:\Users\user\current-link-payroll`. Make the smallest change needed.
Follow existing patterns in the surrounding code.

**Step 2 — Verify syntax (mandatory)**
```powershell
python -c "import ast; ast.parse(open('app/routes.py', encoding='utf-8').read()); print('OK')"
```
Adjust filename to every edited `.py`. For Jinja templates, run a jinja parse check.
Run any project tests: `pytest` (project has `tests/` + `pytest.ini`).

**Step 3 — Commit & push**
```powershell
git add <files>
git commit -m "type: short description"
git push origin main
```

**Step 4 — Deploy with the helper**
```powershell
python deploy_helper.py
```
This does (in order, on the server):
1. `cp -r app app_backup_$(date +%F_%H%M)` and prunes to last 5 backups
2. `git fetch origin main && git reset --hard origin/main`
3. `.venv/bin/pip install -r requirements.txt --quiet`
4. `systemctl restart current-link`
5. Prints `systemctl status` + `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:7860/login`

**Success criteria**: service `active (running)` and HTTP status **200**.

**To run arbitrary server commands** (e.g. check logs, inspect DB):
```powershell
$cmd = @'
journalctl -u current-link.service --no-pager -n 50
'@
$cmd | python ssh_run.py
```

---

## 7. Common operations

### Check app logs
```powershell
$cmd = @'
journalctl -u current-link.service --no-pager -n 100
'@
$cmd | python ssh_run.py
```

### Restart app manually
```powershell
$cmd = @'
systemctl restart current-link
'@
$cmd | python ssh_run.py
```

### Check what commit is live
```powershell
$cmd = @'
cd /opt/current-link/app && git log --oneline -1
'@
$cmd | python ssh_run.py
```

### Local smoke test (no server)
```powershell
python serve.py
```
Then open `http://127.0.0.1:7860`.

---

## 8. Recent meaningful changes (for context)

| Commit | Change |
|---|---|
| `c338c6a` | Supplier earnings tab — month filter |
| `d0a5f72` | Driver kata summary — bilingual EN/UR cards, highlighted NET PAYABLE |
| `d8c5121` | Urdu rendering in kata PDF (Noto Naskh Arabic font + reshaper/bidi) |
| `ca40ac6` | Kata full statement — Salary After Deduct = Store − Advances |
| `43da7e3` | Owner fund SOA edit → jumps to source transaction page |
| `36c0f92` | Owner fund SOA — Edit button per transaction |
| `35fea94` | LPO/non-NMDC invoice — unlimited decimals qty, 4-decimal print |
| `644a212` | Employee join-date NotNullViolation fix + prorata date picker |
| `364ed5b` | Bulk fuel entry form |

---

## 9. Gotchas / notes for agents

- **Endianness of DB differences**: PostgreSQL is stricter than SQLite (NOT NULL,
  ON CONFLICT). Test changes against both `SQLITE_SCHEMA` and `POSTGRES_SCHEMA`
  schema definitions in `app/database.py` when touching schema/SQL.
- **PDFs** are generated with ReportLab in `app/pdf_service.py`; Urdu text needs
  the registered Noto Naskh Arabic TTF at `app/static/fonts/` + `arabic_reshaper`
  + `python-bidi` (both pinned in `requirements.txt`).
- **Never commit** `.env`, *.db, `generated/`, uploads, or backup dumps.
- **Upload size** is capped at 50 MB at the Nginx layer.
- The repo root contains leftover dev scripts (`fix_*.py`, `check_*.py`,
  `dot_*.py`); ignore them unless explicitly asked about them.
- Currency formatting in PDFs: `format_currency()` in `pdf_service.py`.
- Blueprints registered in `app/__init__.py`: `core`, `documents`, `hr`, `fleet`,
  `supplier`, `customer`, `ai`.

---

*Generated for Current Link Payroll. Update this file whenever the infra changes
(new server, new creds, new domain, changed DB backend).*