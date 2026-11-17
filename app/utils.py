"""Shared utility helpers for Current Link ERP.

Extracted from duplicated code across routes.py, supplier/routes.py,
customer/routes.py, and pdf_service.py.
"""
from __future__ import annotations

import re
from typing import Optional


# ── VAT / Tax ───────────────────────────────────────────────────

def calc_vat(net_amount: float, rate: float = 0.05) -> dict:
    """Calculate VAT and total from a net amount.

    Returns dict with keys: net, vat, total.
    """
    vat = round(net_amount * rate, 2)
    total = round(net_amount + vat, 2)
    return {"net": net_amount, "vat": vat, "total": total}


# ── Number to Words (AED) ──────────────────────────────────────

_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven",
         "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen",
         "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty",
         "Seventy", "Eighty", "Ninety"]


def _chunk_to_words(n: int) -> str:
    if n == 0:
        return ""
    if n < 20:
        return _ONES[n]
    if n < 100:
        return (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "")).strip()
    return (_ONES[n // 100] + " Hundred" +
            (" and " + _chunk_to_words(n % 100) if n % 100 else ""))


def num_to_words(amount: float) -> str:
    """Convert a number to words in AED currency format.

    Example: 1234.56 → 'One Thousand Two Hundred and Thirty Four Dirhams and 56 Fils'
    """
    if amount < 0:
        return "Minus " + num_to_words(-amount)

    int_part = int(amount)
    fils = round((amount - int_part) * 100)

    if int_part == 0:
        words = "Zero"
    else:
        parts = []
        if int_part >= 1_000_000:
            parts.append(_chunk_to_words(int_part // 1_000_000) + " Million")
            int_part %= 1_000_000
        if int_part >= 1_000:
            parts.append(_chunk_to_words(int_part // 1_000) + " Thousand")
            int_part %= 1_000
        if int_part >= 100:
            parts.append(_chunk_to_words(int_part // 100) + " Hundred")
            int_part %= 100
        if int_part > 0:
            if parts:
                parts.append("and " + _chunk_to_words(int_part))
            else:
                parts.append(_chunk_to_words(int_part))
        words = " ".join(parts)

    result = words + " Dirhams"
    if fils > 0:
        result += f" and {fils:02d} Fils"
    return result


# ── Company Profile Helper ──────────────────────────────────────

_COMPANY_COLS = (
    "id, company_name, legal_name, trade_license_no, trade_license_expiry, "
    "trn_no, vat_status, address, phone_number, email, bank_name, "
    "bank_account_name, bank_account_number, iban, swift_code, "
    "invoice_terms, base_currency, logo_data, logo_type, theme_color, "
    "e_invoice_start_date, financial_year_label, financial_year_start, financial_year_end"
)


def get_company_profile(db, company_id=None) -> Optional[dict]:
    """Fetch a company_profile row.

    - company_id given → that company
    - company_id None → session-selected company (admin switcher); falls back
      to the lowest id (Current Link) when no session / row missing.
    """
    try:
        cid = int(company_id) if company_id else active_company_id()
        row = db.execute(
            f"SELECT {_COMPANY_COLS} FROM company_profile WHERE id = ?",
            (cid,),
        ).fetchone()
        if not row and not company_id:
            row = db.execute(
                f"SELECT {_COMPANY_COLS} FROM company_profile ORDER BY id ASC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def get_default_company(db) -> Optional[dict]:
    """Ownership fallback = Current Link (lowest id), ignores session."""
    try:
        row = db.execute(
            f"SELECT {_COMPANY_COLS} FROM company_profile ORDER BY id ASC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def active_company_id() -> int:
    """Always Current Link (1) — the admin company switcher was removed;
    stale sessions carrying another company_id are ignored."""
    return 1


_scope_cols_checked = False


def ensure_company_scope_columns(db) -> None:
    """Idempotently add customers/suppliers.company_id when a non-blueprint
    caller (reports center, global search) queries them before any
    customer/supplier page has run its own _ensure_tables() migration.

    Runs at most once per process: /api/search fires this on every keystroke
    and the ALTERs are pure overhead after the first success."""
    global _scope_cols_checked
    if _scope_cols_checked:
        return
    pg = getattr(db, "backend", "") == "postgres"
    ok = True
    for tbl in ("customers", "suppliers"):
        ddl = (
            f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS company_id INTEGER DEFAULT 1"
            if pg
            else f"ALTER TABLE {tbl} ADD COLUMN company_id INTEGER DEFAULT 1"
        )
        try:
            db.execute(ddl)
            db.commit()
        except Exception as e:
            msg = str(e).lower()
            if "already exists" in msg or "duplicate column" in msg:
                pass  # column present — nothing to do
            else:
                ok = False  # table missing / transient — retry next call
            try:
                db.rollback()
            except Exception:
                pass
    if ok:
        _scope_cols_checked = True


def get_active_company(db) -> Optional[dict]:
    """Company profile for the session-selected company (switcher)."""
    return get_company_profile(db, active_company_id())


def list_companies(db) -> list:
    """All company_profile rows for the switcher dropdown."""
    try:
        rows = db.execute(
            f"SELECT {_COMPANY_COLS} FROM company_profile ORDER BY id ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def company_short_name(name: Optional[str]) -> str:
    """Short sidebar label for a company (docs/PDFs keep the full legal name).

    CURRENT LINK → "Current Link", EAGLE MOUNTAIN → "Eagle Mountain";
    other names longer than 22 chars are cut to their first two words.
    """
    nm = (name or "").strip()
    if not nm:
        return "Current Link"
    up = nm.upper()
    if up.startswith("EAGLE MOUNTAIN"):
        return "Eagle Mountain"
    if up.startswith("CURRENT LINK"):
        return "Current Link"
    if len(nm) <= 22:
        return nm
    parts = nm.split()
    if len(parts) >= 2:
        short = " ".join(parts[:2])
        return short.title() if short.isupper() else short
    return nm


def get_company_for_vehicle(db, plate_no) -> Optional[dict]:
    """Resolve company from a vehicle plate. Falls back to default company."""
    try:
        if plate_no:
            row = db.execute(
                f"SELECT cp.id, cp.company_name, cp.legal_name, cp.trade_license_no, "
                f"cp.trade_license_expiry, cp.trn_no, cp.vat_status, cp.address, "
                f"cp.phone_number, cp.email, cp.bank_name, cp.bank_account_name, "
                f"cp.bank_account_number, cp.iban, cp.swift_code, cp.invoice_terms, "
                f"cp.base_currency, cp.logo_data, cp.logo_type, cp.theme_color "
                f"FROM vehicles v JOIN company_profile cp ON cp.id = v.company_id "
                f"WHERE v.plate_no = ?",
                (str(plate_no).strip(),),
            ).fetchone()
            if row:
                return dict(row)
    except Exception:
        pass
    return get_default_company(db)


def get_company_for_employee(db, employee_id) -> Optional[dict]:
    """Resolve company from employee/driver current vehicle. Fallback = default."""
    try:
        eid = str(employee_id or "").strip()
        if not eid:
            return get_default_company(db)
        # Preferred: denormalized drivers.vehicle_no
        row = db.execute(
            f"SELECT v.company_id FROM drivers d JOIN vehicles v ON v.plate_no = d.vehicle_no "
            f"WHERE d.driver_id = ?",
            (eid,),
        ).fetchone()
        if not row or not row["company_id"]:
            row = db.execute(
                f"SELECT v.company_id FROM vehicle_assignments va "
                f"JOIN vehicles v ON v.plate_no = va.vehicle_id "
                f"WHERE va.driver_id = ? AND va.is_current = 1 "
                f"ORDER BY va.id DESC LIMIT 1",
                (eid,),
            ).fetchone()
        if row and row["company_id"]:
            cp = get_company_profile(db, row["company_id"])
            if cp:
                return cp
    except Exception:
        pass
    return get_default_company(db)


# ── Date Filter Builder ────────────────────────────────────────

def build_date_filter(
    base_where: str,
    date_from: str = "",
    date_to: str = "",
    month: str = "",
    date_col: str = "entry_date",
) -> tuple[str, list]:
    """Build a date filter clause and params list.

    Returns (where_clause_with_AND, params_list).
    """
    conditions = []
    params = []

    if month:
        conditions.append(f"LEFT({date_col}, 7) = ?")
        params.append(month)
    elif date_from:
        conditions.append(f"{date_col} >= ?")
        params.append(date_from)
        if date_to:
            conditions.append(f"{date_col} <= ?")
            params.append(date_to)
    elif date_to:
        conditions.append(f"{date_col} <= ?")
        params.append(date_to)

    if conditions:
        return base_where + " AND " + " AND ".join(conditions), params
    return base_where, params


# ── Sanitize filename ──────────────────────────────────────────

def sanitize_filename(name: str) -> str:
    """Remove unsafe characters from a filename."""
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip().strip('.')


# ── Money Formatting ───────────────────────────────────────────

def fmt_money(value, decimals: int = 2) -> str:
    """Format an amount with thousands separators; invalid → 0.00."""
    try:
        return f"{float(value or 0):,.{decimals}f}"
    except (TypeError, ValueError):
        return f"0.{'0' * decimals}"


def fmt_money_aed(value, decimals: int = 2) -> str:
    """Format as 'AED 1,234.56'."""
    return f"AED {fmt_money(value, decimals)}"


def rate_fmt(value) -> str:
    """Unit-rate display: 2 decimals by default, but keeps a 3rd/4th decimal
    when the value actually has one (0.093 stays 0.093, not 0.09)."""
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return str(value or "0")
    s4 = f"{v:,.4f}"
    if "." in s4:
        frac = s4.split(".", 1)[1].rstrip("0")
        if len(frac) > 2:
            return s4.rstrip("0").rstrip(".")
    return f"{v:,.2f}"
