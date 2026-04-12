---
title: Current Link Payroll
emoji: "🚛"
colorFrom: blue
colorTo: yellow
sdk: docker
app_port: 7860
---

# Current Link Driver Payroll System

## Overview

Current Link is a driver-focused payroll and operations system for:

- driver master management
- transactions and advances
- salary store and salary slip generation
- owner fund tracking
- driver self-service portal
- PDF output for salary slips, KATA, and timesheets

## Security Setup

This project no longer keeps production secrets inside source code.

Create a local `.env` file based on `.env.example`:

```text
SECRET_KEY=replace-with-a-long-random-secret
ADMIN_PASSWORD=replace-with-admin-password
ADMIN_PASSWORD_HASH=
OWNER_PASSWORD=replace-with-owner-password
OWNER_PASSWORD_HASH=
DATABASE_FILE=payroll.db
REQUIRE_DATABASE_URL=false
LOGIN_MAX_ATTEMPTS=5
LOGIN_LOCK_MINUTES=15
SESSION_COOKIE_SECURE=false
```

## Roles

- `Admin`
  - password comes from `ADMIN_PASSWORD` or `ADMIN_PASSWORD_HASH`
  - full access to drivers, payroll, transactions, imports, and owner fund
- `Owner`
  - access code comes from `OWNER_PASSWORD` or `OWNER_PASSWORD_HASH`
  - owner fund and owner reporting access
- `Driver`
  - login with registered phone number and driver PIN
  - access timesheet, salary slips, and transaction history

## Driver Security

- Driver login requires:
  - registered phone number
  - driver PIN
- Driver PIN is set from the add/edit driver form
- Driver PIN is stored as a secure password hash
- Admin and Owner passwords can also be stored as Werkzeug password hashes
- Login attempts are rate-limited with temporary lockouts after repeated failures

## Main Features

- Admin, Owner, and Driver portals
- Driver phone + PIN self-service login
- CSRF protection for forms
- Strict numeric validation for money and hours
- Driver create, edit, active/inactive, and delete
- Driver transactions with edit/delete
- Salary store with duplicate-month update protection
- OT month is saved automatically as previous month of the salary month
- Salary slip PDF with duplicate generation protection
- Driver KATA PDF
- Owner Fund page and Owner Fund PDF
- Owner Fund create, edit, and delete
- Driver timesheet entry and timesheet PDF
- Import from `Currentlink.xlsm`
- Import from uploaded `Driver.pdf`
- Mobile-friendly driver portal
- Landing page plus dedicated services page

## Driver Folders

Generated assets are stored inside:

- `generated/drivers/<driver-name>__<driver-id>/salary_slips`
- `generated/drivers/<driver-name>__<driver-id>/kata_pdfs`
- `generated/drivers/<driver-name>__<driver-id>/timesheets`
- `generated/drivers/<driver-name>__<driver-id>/profile`

## Local Run

1. Install dependencies:

```powershell
py -m pip install -r requirements.txt
```

2. Start the app:

```powershell
py serve.py
```

3. Open:

```text
http://127.0.0.1:5000
```

You can also use:

- `start_current_link.bat`

## Tests

Run the basic workflow tests:

```powershell
py -m pytest -q
```

Current tests cover:

- driver login rules
- admin login hash and rate-limit rules
- salary store update rules
- OT month previous-month rule
- transaction validation
- driver delete cleanup
- owner fund edit and delete

## Public Deployment Ready

This project includes:

- `serve.py`
- `waitress`
- `Dockerfile`
- `.dockerignore`
- `render.yaml`
- `railway.json`
- `Procfile`

### Hugging Face Spaces

1. Create a new Space on Hugging Face
2. Choose `Docker` as the Space SDK
3. Import or push this repository into the Space
4. In Space `Settings -> Variables and secrets`, set:
   - `SECRET_KEY`
   - `ADMIN_PASSWORD` or `ADMIN_PASSWORD_HASH`
   - `OWNER_PASSWORD` or `OWNER_PASSWORD_HASH`
   - `SESSION_COOKIE_SECURE=true`
   - `REQUIRE_DATABASE_URL=false` for demo use
5. The Space reads the included `Dockerfile` and serves the app on port `7860`

Important:

- Free Spaces do not provide durable local storage for long-term business data
- For real public use, connect an external Postgres database and store generated files outside local disk

## Deploy Notes

### Render

1. Push project to GitHub
2. Create a new Web Service on Render
3. Use:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python serve.py`
4. Add Render Postgres and set `DATABASE_URL`
5. Set `SECRET_KEY`, `ADMIN_PASSWORD` or `ADMIN_PASSWORD_HASH`, and `OWNER_PASSWORD` or `OWNER_PASSWORD_HASH`
6. Set `REQUIRE_DATABASE_URL=true` for public production deployment

### Railway

1. Push project to GitHub
2. Create a Railway project
3. Use `railway.json`
4. Set `DATABASE_URL`, `SECRET_KEY`, `ADMIN_PASSWORD`, and `OWNER_PASSWORD`

### Docker / VPS

```powershell
docker build -t current-link-payroll .
docker run -p 5000:5000 current-link-payroll
```

## Data Safety

- Local SQLite is suitable for local/offline use
- Public hosting should use `DATABASE_URL` with Postgres
- Driver photos are stored in the database as well as generated files
- Salary slips can be rebuilt from saved payroll data if the PDF file is missing

## Important Note

If the system must work from any network or any city/site, deploy it on a public server with:

- public domain or public URL
- Postgres database
- environment variables for secrets
- HTTPS enabled
