# PDF Design System

Professional A4 PDF templates for ERP/business documents. Built with ReportLab.

## Files

| File | Description |
|------|-------------|
| `base_design.py` | Colors, fonts, helper functions (shared by all templates) |
| `customer_invoice_live.py` | **Customer Tax Invoice** (exact live format from system) |
| `lpo_design.py` | Local Purchase Order (LPO) |
| `quotation_design.py` | Customer Quotation |
| `soa_design.py` | Statement of Account |
| `salary_slip_design.py` | Employee Salary Slip |
| `kata_design.py` | Driver Statement (Kata) |
| `fuel_report_design.py` | Fuel Consumption Report |

## Quick Start — Customer Invoice (Live Format)

```python
from customer_invoice_live import generate_customer_invoice_pdf

# Company profile (from your settings/database)
company = {
    "company_name": "YOUR COMPANY NAME",
    "address": "Address, City, UAE",
    "phone_number": "+971-XX-XXX-XXXX",
    "email": "info@company.com",
    "trn_no": "123456789012345",
    "theme_color": "#1a3a5c",       # header/accent color
    "logo_data": "base64-string",   # optional
    "bank_name": "Emirates NBD",
    "bank_account_name": "YOUR COMPANY",
    "bank_account_number": "123456789",
    "iban": "AE123456789012345678901",
    "swift_code": "EBILAEAD",
}

customer = {
    "customer_name": "Customer Name",
    "trn": "987654321098765",
    "phone": "+971-XX-XXX-XXXX",
    "email": "customer@email.com",
    "address": "Customer Address",
}

invoice = {
    "invoice_no": "INV-2026/001",
    "invoice_date": "2026-09-01",
    "amount": 10000.00,
    "vat_percent": 5.0,
    "vat_amount": 500.00,
    "total_amount": 10500.00,
    "notes": "Thank you for your business",
    "so_no": "SO-2026/001",      # optional
    "lpo_no": "LPO-2026/001",    # optional
}

items = [
    {
        "description": "Transport Service - Month of August",
        "quantity": 1,
        "rate": 10000.00,
        "amount": 10000.00,
        "unit": "mo",
        "vat_percent_item": 5.0,
        "vat_amount_item": 500.00,
        "total_incl_vat": 10500.00,
        "vehicle_no": "CCQ-1234",  # optional
    },
]

pdf_path = generate_customer_invoice_pdf(
    company=company,
    customer=customer,
    invoice=invoice,
    items=items,
    output_dir="./output",
    logo_path="logo.png",        # optional
    stamp_path="Stamp.png",      # optional
    sign_path="Sign.png",        # optional
)
```

## What's Inside the Invoice PDF

```
┌──────────────────────────────────────────────────────┐
│  [LOGO]  Company Name                     TAX INVOICE│
│          Address · Phone · Email          # INV-001  │
│          TRN: 12345                       01-Sep-2026│
│  ═══════════════════════════════════════════════════  │
│                                                      │
│  ┌─ BILL TO ──────────┐  ┌─ INVOICE INFO ─────────┐ │
│  │ Customer: Name     │  │ Invoice #: INV-2026/001 │ │
│  │ TRN: 9876543210    │  │ Date: 01-Sep-2026       │ │
│  │ Phone: +971-XX     │  │ SO No.: SO-2026/001     │ │
│  │ Address: ...       │  │ LPO No.: LPO-2026/001   │ │
│  └────────────────────┘  └─────────────────────────┘ │
│                                                      │
│  ┌──────────────────────────────────────────────────┐│
│  │ # │ Description │ Qty │ Unit │ Price │ VAT │ Total││
│  ├───┼─────────────┼─────┼──────┼───────┼─────┼──────┤│
│  │ 1 │ Service     │ 1   │ mo   │10,000 │ 5%  │10,500││
│  └──────────────────────────────────────────────────┘│
│                                                      │
│  Sub Total                          AED 10,000.00    │
│  VAT @ 5%                              AED 500.00    │
│  ─────────────────────────────────────────────────── │
│  Total Due                       AED 10,500.00       │
│                                                      │
│  Amount in Words: AED Ten Thousand and 00/100 Only   │
│                                                      │
│  BANK DETAILS                                        │
│  Bank: Emirates NBD | A/C: 123456789                 │
│  IBAN: AE123456789012345678901                       │
│                                                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │ ____________│  │  [STAMP]    │  │  [SIGN]     │  │
│  │  [STAMP]    │  │  ___________│  │ ____________│  │
│  │  [SIGN]     │  │             │  │             │  │
│  │ Authorized  │  │             │  │             │  │
│  │ Signatory   │  │             │  │             │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  │
│                                                      │
│  ═══════════════════════════════════════════════════  │
│  This is a computer-generated Tax Invoice.           │
└──────────────────────────────────────────────────────┘
```

## Color Palette

```python
TH  = "#1a3a5c"    # Theme color (header, totals line)
WH  = white         # White
BG  = "#f8fafc"     # Light background
C3  = "#e2e8f0"     # Borders
C4  = "#0f172a"     # Dark text
C5  = "#64748b"     # Muted text
C6  = "#dc2626"     # Red (VAT amount)
DH  = "#1e293b"     # Table header background
```

## Dependencies

```
reportlab>=4.0
Pillow>=9.0  (optional, for logo sizing)
```

## Notes

- All dimensions use `mm` (millimeters) for A4 page
- Font: Helvetica (built-in, no external fonts needed)
- Logo: Pass as base64 in `logo_data` OR as file path in `logo_path`
- Stamp/Sign: Pass as file paths (optional)
- Bank details: Included automatically if provided in company dict
- Output directory is created automatically
