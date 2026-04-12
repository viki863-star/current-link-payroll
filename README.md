# Current Link Driver Payroll System

## Main Features

- Admin, Owner, and Driver login
- Driver phone-number self service
- Driver timesheet entry
- Driver transactions
- Salary store with month update protection
- Salary slip PDF with duplicate-slip protection
- Driver KATA PDF
- Owner Fund Kata page and PDF
- Mobile-friendly driver portal
- Import from `Currentlink.xlsm`

## Roles

- `Admin`
  - Password: `current2324`
  - Full access
- `Owner`
  - Access code: `current2324`
  - Owner Fund page and Owner Fund PDF
- `Driver`
  - Login with phone number saved in driver master
  - Timesheet, salary slips, transactions

## Driver Folders

- `generated/drivers/<DRIVER_ID>/salary_slips`
- `generated/drivers/<DRIVER_ID>/kata_pdfs`
- `generated/drivers/<DRIVER_ID>/profile`

## Local Run

1. `py -m pip install -r requirements.txt`
2. `py serve.py`
3. Open `http://127.0.0.1:5000`

Or double-click:

- `start_current_link.bat`

## Public Deployment Ready

This project now includes:

- `serve.py` for production-style serving
- `waitress` in `requirements.txt`
- `Dockerfile`
- `.dockerignore`
- `render.yaml`
- `railway.json`
- `Procfile`

## Mobile / PWA

- Drivers can use the portal on mobile browser
- Installable app files are included:
  - `app/static/manifest.webmanifest`
  - `app/static/service-worker.js`
  - `app/static/icon-192.svg`
  - `app/static/icon-512.svg`

## Deploy Options

### Render

1. Push project to GitHub
2. Create new Web Service on Render
3. Render can read `render.yaml` automatically
4. Start command: `python serve.py`

### Railway

1. Push project to GitHub
2. Create project in Railway
3. Railway can use `railway.json`
4. Start command: `python serve.py`

### Docker / VPS

```powershell
docker build -t current-link-payroll .
docker run -p 5000:5000 current-link-payroll
```

## Important Note

If you want the system to work from `any network` or `any city/site`, the app must be deployed on a public server or cloud VPS with a domain or public IP. Running on a local PC only gives local/LAN access.
