"""Current Link ERP — User Guide PDF Generator"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from datetime import datetime
import os

# ── Colors ──────────────────────────────────────────────────────
PRIMARY   = HexColor("#1c568b")
DARK      = HexColor("#0f172a")
ORANGE    = HexColor("#e65100")
GREEN     = HexColor("#16a34a")
LIGHT_BG  = HexColor("#f8fafc")
BLUE_BG   = HexColor("#eff6ff")
GREEN_BG  = HexColor("#f0fdf4")
ORANGE_BG = HexColor("#fff7ed")
PURPLE_BG = HexColor("#faf5ff")
GRAY      = HexColor("#64748b")
LINE      = HexColor("#e2e8f0")
WHITE     = HexColor("#ffffff")

# ── Styles ──────────────────────────────────────────────────────
styles = getSampleStyleSheet()

cover_title = ParagraphStyle("cover_title", parent=styles["Title"],
    fontSize=32, leading=38, textColor=WHITE, alignment=TA_CENTER,
    spaceAfter=8, fontName="Helvetica-Bold")

cover_sub = ParagraphStyle("cover_sub", parent=styles["Normal"],
    fontSize=14, leading=18, textColor=HexColor("#bfdbfe"), alignment=TA_CENTER,
    fontName="Helvetica")

section_title = ParagraphStyle("section_title", parent=styles["Heading1"],
    fontSize=20, leading=26, textColor=PRIMARY, spaceBefore=16, spaceAfter=10,
    fontName="Helvetica-Bold")

subsection = ParagraphStyle("subsection", parent=styles["Heading2"],
    fontSize=13, leading=17, textColor=DARK, spaceBefore=10, spaceAfter=6,
    fontName="Helvetica-Bold")

body = ParagraphStyle("body", parent=styles["Normal"],
    fontSize=10, leading=14, textColor=DARK, alignment=TA_JUSTIFY,
    spaceAfter=6, fontName="Helvetica")

bullet = ParagraphStyle("bullet", parent=body,
    leftIndent=18, bulletIndent=6, spaceAfter=3)

small = ParagraphStyle("small", parent=body, fontSize=8.5, leading=11, textColor=GRAY)

table_header = ParagraphStyle("th", parent=body,
    fontSize=9, leading=12, textColor=WHITE, fontName="Helvetica-Bold")

table_cell = ParagraphStyle("tc", parent=body,
    fontSize=9, leading=12, textColor=DARK)

# ── Helper ──────────────────────────────────────────────────────
def hr():
    return HRFlowable(width="100%", thickness=0.5, color=LINE, spaceAfter=10, spaceBefore=6)

def feature_table(rows):
    """rows = list of (feature_name, description)"""
    data = [[Paragraph("Feature", table_header), Paragraph("Description", table_header)]]
    for f, d in rows:
        data.append([Paragraph(f, table_cell), Paragraph(d, table_cell)])
    t = Table(data, colWidths=[140, 350])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("BACKGROUND", (0, 1), (-1, -1), WHITE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_BG]),
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t

def module_box(title, items, color):
    """Colored box with module title and bullet list"""
    content = [[Paragraph(f"<b>{title}</b>", ParagraphStyle("mb", parent=body,
        fontSize=11, leading=14, textColor=color, fontName="Helvetica-Bold"))]]
    for item in items:
        content.append([Paragraph(f"  •  {item}", bullet)])
    t = Table(content, colWidths=[480])
    bg = {PRIMARY: BLUE_BG, GREEN: GREEN_BG, ORANGE: ORANGE_BG}.get(color, LIGHT_BG)
    border = {PRIMARY: HexColor("#bfdbfe"), GREEN: HexColor("#bbf7d0"), ORANGE: HexColor("#fed7aa")}.get(color, LINE)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("BOX", (0, 0), (-1, -1), 1, border),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    return t

# ── Build PDF ───────────────────────────────────────────────────
OUTPUT = os.path.join(os.path.dirname(__file__), "CurrentLink_ERP_UserGuide.pdf")

doc = SimpleDocTemplate(OUTPUT, pagesize=A4,
    leftMargin=20*mm, rightMargin=20*mm, topMargin=15*mm, bottomMargin=15*mm)

story = []
W = A4[0] - 40*mm  # usable width

# ── COVER PAGE ──────────────────────────────────────────────────
cover_bg = Table(
    [[Spacer(1, 80*mm)],
     [Paragraph("Current Link", cover_title)],
     [Paragraph("General Contracting", ParagraphStyle("cs2", parent=cover_sub, fontSize=18))],
     [Spacer(1, 10*mm)],
     [Paragraph("ERP System — User Guide", ParagraphStyle("cs3", parent=cover_sub, fontSize=16, textColor=WHITE))],
     [Spacer(1, 6*mm)],
     [Paragraph(f"Version 1.0  •  {datetime.now().strftime('%B %Y')}", cover_sub)],
     [Spacer(1, 40*mm)],
     [Paragraph("www.currentlinkgc.com", ParagraphStyle("cs4", parent=cover_sub, fontSize=11, textColor=HexColor("#93c5fd")))],
     [Spacer(1, 8*mm)]],
    colWidths=[W + 40*mm]
)
cover_bg.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, -1), PRIMARY),
    ("TOPPADDING", (0, 0), (-1, -1), 0),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ("LEFTPADDING", (0, 0), (-1, -1), 20),
    ("RIGHTPADDING", (0, 0), (-1, -1), 20),
    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("ROUNDEDCORNERS", [12, 12, 12, 12]),
]))
story.append(cover_bg)
story.append(PageBreak())

# ── TABLE OF CONTENTS ───────────────────────────────────────────
story.append(Paragraph("Table of Contents", section_title))
story.append(hr())
toc_items = [
    ("1.", "Dashboard & Overview"),
    ("2.", "Fleet Management"),
    ("3.", "HR & Employee Management"),
    ("4.", "Salary & Payments"),
    ("5.", "Supplier Management"),
    ("6.", "Customer Management"),
    ("7.", "Documents Management"),
    ("8.", "Financial Tools"),
    ("9.", "Reports & PDF Generation"),
    ("10.", "AI Assistant"),
    ("11.", "Backup & Security"),
]
for num, item in toc_items:
    story.append(Paragraph(f"<b>{num}</b>  {item}", ParagraphStyle("toc", parent=body, fontSize=12, leading=20, leftIndent=10)))
story.append(Spacer(1, 10*mm))
story.append(Paragraph("This document describes all modules and features available in the Current Link ERP system.", body))
story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════════
# 1. DASHBOARD
# ═══════════════════════════════════════════════════════════════════
story.append(Paragraph("1. Dashboard & Overview", section_title))
story.append(hr())
story.append(Paragraph("The main dashboard provides a real-time overview of the entire business at a glance.", body))
story.append(Spacer(1, 4*mm))
story.append(module_box("Dashboard Features", [
    "Summary cards: Total Drivers, Vehicles, Active Vehicles, Supplier Balance, Pending Salaries, Active Customers",
    "Global cross-module search across all data",
    "Real-time in-app notifications (info, warning, error, success)",
    "Quick navigation to all modules",
    "Company profile with logo and branding",
], PRIMARY))
story.append(Spacer(1, 6*mm))

story.append(module_box("Authentication & Access Control", [
    "Admin login with CSRF protection and rate limiting",
    "Field Staff portal (separate login for field technicians)",
    "Supplier portal (suppliers can view their own data)",
    "Technician portal (technicians can submit jobs and papers)",
    "Role-based access control throughout the system",
], PRIMARY))
story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════════
# 2. FLEET MANAGEMENT
# ═══════════════════════════════════════════════════════════════════
story.append(Paragraph("2. Fleet Management", section_title))
story.append(hr())
story.append(Paragraph("Complete vehicle lifecycle management with 33+ vehicle types, linked Head-Trailer system, and real-time tracking.", body))
story.append(Spacer(1, 4*mm))

story.append(Paragraph("<b>2.1 Vehicle Management</b>", subsection))
story.append(feature_table([
    ("Vehicle CRUD", "Add, edit, view, delete vehicles with 33 types (tractors, trailers, tankers, trucks, buses, cranes, excavators, etc.)"),
    ("Vehicle Profile", "Comprehensive profile page with tabs: Overview, Driver, Jobs, Maintenance, Fuel, Parts, Documents"),
    ("Vehicle Categories", "Head, Trailer, and custom categories with sub-types"),
    ("Vehicle Status", "Active/Inactive status tracking with filter tabs"),
    ("Head-Trailer Linking", "Link trailers to head vehicles with link types (Flat, Tank, Lowbed, etc.)"),
    ("Linked Vehicle Management", "Direct link/unlink/change from vehicle profile page"),
    ("Custom Fields", "\"Type your own\" option for all dropdown fields (vehicle type, ownership, category, etc.)"),
    ("Partner Management", "Partnership ownership with percentage splits"),
    ("Vehicle Search", "Search by plate number, type, model, or driver name"),
]))
story.append(Spacer(1, 4*mm))

story.append(Paragraph("<b>2.2 Maintenance Jobs</b>", subsection))
story.append(feature_table([
    ("Job Submission", "Field staff submit maintenance jobs with descriptions and photos"),
    ("Admin Direct Entry", "Admin can add jobs directly for any vehicle"),
    ("Approval Workflow", "Pending → Approved/Rejected status tracking"),
    ("Bulk Approve", "Approve all jobs at once or per-staff batch approval"),
    ("Photo Attachments", "Upload and view job photos with thumbnail preview"),
    ("Job History", "Complete maintenance history per vehicle"),
]))
story.append(Spacer(1, 4*mm))

story.append(Paragraph("<b>2.3 Maintenance Papers</b>", subsection))
story.append(feature_table([
    ("Paper Tracking", "Multi-item maintenance papers with line items"),
    ("Bulk Creation", "Create multiple papers from field staff submissions"),
    ("Tax Modes", "Tax Invoice / Without Tax selection per paper"),
    ("Supplier Linking", "Link papers to suppliers with TRN and bill numbers"),
    ("Settlement", "Track paper settlements and payments"),
]))
story.append(Spacer(1, 4*mm))

story.append(Paragraph("<b>2.4 Fuel Management</b>", subsection))
story.append(feature_table([
    ("Fuel Entries", "Record fuel purchases per vehicle (single + bulk multi-vehicle)"),
    ("Fuel Reports", "PDF fuel reports with date/vehicle filters"),
    ("Fuel Supplier Statement", "Statement of account for fuel suppliers"),
    ("VAT Management", "Quick VAT tracking for fuel purchases"),
]))
story.append(Spacer(1, 4*mm))

story.append(Paragraph("<b>2.5 Field Staff</b>", subsection))
story.append(feature_table([
    ("Staff Profiles", "CRUD with photo, username/password for portal access"),
    ("Staff Jobs", "View all jobs submitted by each staff member"),
    ("Staff Papers", "View all maintenance papers by staff"),
    ("Staff Advances", "Track advances given to field staff"),
    ("Cash Receipts", "Record cash receipts from staff"),
    ("Date/Vehicle Filters", "Filter staff data by date range or vehicle"),
    ("PDF Exports", "Export staff reports, advances, and jobs as PDF"),
]))
story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════════
# 3. HR & EMPLOYEES
# ═══════════════════════════════════════════════════════════════════
story.append(Paragraph("3. HR & Employee Management", section_title))
story.append(hr())
story.append(Paragraph("Full human resource management system for drivers, operators, and staff.", body))
story.append(Spacer(1, 4*mm))

story.append(Paragraph("<b>3.1 Employee Master</b>", subsection))
story.append(feature_table([
    ("Employee CRUD", "Add, edit, view employees with types: Driver, Crane Operator, Field Staff, Helper, Accountant, etc."),
    ("Employee Types", "Multiple employee categories with status tracking"),
    ("Search & Filter", "Search by name, ID, department, status, or assigned vehicle"),
    ("Restore Deleted", "Restore employees from soft delete (technicians table)"),
    ("Excel Export", "Download employee list as Excel spreadsheet"),
    ("PDF Export", "Download employee list as formatted PDF"),
    ("Photo Management", "Employee photo upload and display"),
]))
story.append(Spacer(1, 4*mm))

story.append(Paragraph("<b>3.2 Document Management</b>", subsection))
story.append(feature_table([
    ("Employee Documents", "Upload and manage employee documents (visa, license, passport, etc.)"),
    ("Expiry Tracking", "Track document expiry dates with color-coded status badges"),
    ("Thumbnail Generation", "Auto-generate thumbnails for uploaded documents"),
    ("ZIP Export", "Download all documents as a ZIP archive"),
]))
story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════════
# 4. SALARY & PAYMENTS
# ═══════════════════════════════════════════════════════════════════
story.append(Paragraph("4. Salary & Payments", section_title))
story.append(hr())
story.append(Paragraph("Complete payroll system with FIFO advance deduction, salary cards, and payment tracking.", body))
story.append(Spacer(1, 4*mm))

story.append(Paragraph("<b>4.1 Salary Management</b>", subsection))
story.append(feature_table([
    ("Salary Dashboard", "Month-wise status view: Paid, Unpaid, Pending, No Record"),
    ("Monthly Salary Store", "Store and edit monthly salary with basic, OT, personal vehicle, prorata calculations"),
    ("Salary Slip Generation", "Generate salary slips with FIFO advance deduction logic"),
    ("Salary Card PDF", "Compact salary card format perfect for WhatsApp sharing"),
    ("Deduction Statement", "Detailed deduction statement PDF per employee"),
    ("Delete Salary Slip", "Delete salary slip with automatic FIFO reversal"),
    ("OT Calculation", "Overtime calculation based on work hours"),
]))
story.append(Spacer(1, 4*mm))

story.append(Paragraph("<b>4.2 Employee Kata (Advance Tracking)</b>", subsection))
story.append(feature_table([
    ("Monthly Kata", "Track advances, deductions, and remaining balance per month"),
    ("Deduction History", "Complete history of all deductions applied"),
    ("Balance Tracking", "Running balance of outstanding advances"),
    ("Kata PDF", "Generate printable kata statement"),
]))
story.append(Spacer(1, 4*mm))

story.append(Paragraph("<b>4.3 FIFO Deduction Logic</b>", subsection))
story.append(Paragraph("The system uses FIFO (First In, First Out) logic for salary deductions. When a salary slip is generated, advances are deducted starting from the oldest transaction line first. This ensures fair and accurate deduction tracking.", body))
story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════════
# 5. SUPPLIER MANAGEMENT
# ═══════════════════════════════════════════════════════════════════
story.append(Paragraph("5. Supplier Management", section_title))
story.append(hr())
story.append(Paragraph("Multi-mode supplier management supporting Online, Cash, Managed, and Partnership operations.", body))
story.append(Spacer(1, 4*mm))

story.append(Paragraph("<b>5.1 Four Supplier Modes</b>", subsection))
story.append(feature_table([
    ("Online (Normal)", "Traditional supplier with assets, timesheets, vouchers, payments — full billing cycle"),
    ("Cash", "Cash-based trips, debits, payments with auto-voucher PDF generation"),
    ("Managed", "Company-managed supplier operations with full control"),
    ("Partnership", "Partnership split calculations, expense tracking, profit distribution"),
]))
story.append(Spacer(1, 4*mm))

story.append(Paragraph("<b>5.2 Online Supplier Features</b>", subsection))
story.append(feature_table([
    ("Assets (Vehicles)", "Register supplier vehicles with rate basis and shift mode"),
    ("Timesheets", "Record work timesheets auto-linked to vouchers"),
    ("Invoice Intake", "Receive and record supplier invoices (by hand entry)"),
    ("Voucher Generation", "Generate billing vouchers from timesheets/submissions"),
    ("Payment Processing", "Record payments against vouchers with auto-sync balance"),
    ("Statement of Account", "View and download SOA with running balance"),
    ("Partnership Entries", "Track expenses, shifts, and profit splits"),
    ("Kata (Cash/Loan)", "Track trips, debits, payments, and balance for cash suppliers"),
]))
story.append(Spacer(1, 4*mm))

story.append(Paragraph("<b>5.3 Supplier Documents & PDFs</b>", subsection))
story.append(feature_table([
    ("LPO (Local Purchase Order)", "Create and download LPO documents with line items"),
    ("Quotation Management", "Create quotations with line items, VAT, and file upload"),
    ("Payment Voucher", "Generate payment voucher PDFs"),
    ("Cheque Print", "Print cheque view for payments"),
    ("Statement of Account PDF", "Full SOA with running balance as PDF"),
    ("Cash Supplier Kata PDF", "Cash supplier kata statement as PDF"),
    ("Partnership Statement", "Partnership statement PDF with expense splits"),
]))
story.append(Spacer(1, 4*mm))

story.append(Paragraph("<b>5.4 Supplier Portal</b>", subsection))
story.append(feature_table([
    ("Self-Service Portal", "Suppliers can log in and view their own data"),
    ("Inquiry System", "Suppliers can submit inquiries/questions"),
    ("Registration Requests", "New suppliers can self-register for admin approval"),
    ("Approve/Reject/Convert", "Admin can approve, reject, or convert registrations to parties"),
]))
story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════════
# 6. CUSTOMER MANAGEMENT
# ═══════════════════════════════════════════════════════════════════
story.append(Paragraph("6. Customer Management", section_title))
story.append(hr())
story.append(Paragraph("Full CRM with invoicing, contracts, quotations, and NMDC-format billing.", body))
story.append(Spacer(1, 4*mm))

story.append(Paragraph("<b>6.1 Customer Master</b>", subsection))
story.append(feature_table([
    ("Customer CRUD", "Add, edit, view customers with auto-generated codes (CUS-XXXX)"),
    ("Logo Upload", "Upload customer company logo"),
    ("TRN & Trade License", "Store TRN number and trade license details"),
    ("Dashboard", "Total customers, receivables, recent invoices/payments, monthly trend, top customers"),
]))
story.append(Spacer(1, 4*mm))

story.append(Paragraph("<b>6.2 Invoicing</b>", subsection))
story.append(feature_table([
    ("Standard Invoicing", "Create and manage standard invoices with line items"),
    ("NMDC Format", "Equipment-based billing with plant/reg/hours and monthly rate conversion"),
    ("Invoice PDF", "Download invoice as PDF (two layouts: standard + NMDC premium)"),
    ("Credit Notes", "Issue credit notes against invoices"),
    ("Invoice History", "Complete invoice history per customer"),
]))
story.append(Spacer(1, 4*mm))

story.append(Paragraph("<b>6.3 Customer Documents</b>", subsection))
story.append(feature_table([
    ("Contracts", "Create and manage customer contracts"),
    ("Quotations", "Create quotations with line items and VAT"),
    ("LPOs", "Local Purchase Orders with file upload and service order linking"),
    ("Service Orders", "Track service orders linked to LPOs"),
    ("Statement of Account", "Full SOA with invoices, payments, credit notes, and balance"),
    ("Tabreed Tripsheets", "Specialized tripsheet management for Tabreed projects"),
]))
story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════════
# 7. DOCUMENTS MANAGEMENT
# ═══════════════════════════════════════════════════════════════════
story.append(Paragraph("7. Documents Management", section_title))
story.append(hr())
story.append(Paragraph("Centralized document storage with Mulkiya tracking, thumbnails, and expiry alerts.", body))
story.append(Spacer(1, 4*mm))

story.append(feature_table([
    ("Document Upload", "Upload documents with categories, expiry dates, and notes"),
    ("Mulkiya Documents", "Vehicle Mulkiya tracking with expiry status (Valid / Expiring Soon / Expired)"),
    ("Thumbnail Generation", "Auto-generate document thumbnails using PIL image processing"),
    ("PDF Preview", "Preview PDF documents directly in the browser"),
    ("Vehicle Documents", "Per-vehicle document storage (Mulkiya + other documents)"),
    ("Employee Documents", "Per-employee document storage (visa, license, passport, etc.)"),
    ("ZIP Export", "Download all documents as a ZIP archive"),
    ("Flip Card Preview", "Visual flip-card preview for Mulkiya documents on vehicle profile"),
]))
story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════════
# 8. FINANCIAL TOOLS
# ═══════════════════════════════════════════════════════════════════
story.append(Paragraph("8. Financial Tools", section_title))
story.append(hr())
story.append(Paragraph("Built-in financial management tools for fund tracking, loans, annual fees, and banking.", body))
story.append(Spacer(1, 4*mm))

story.append(Paragraph("<b>8.1 Owner Fund</b>", subsection))
story.append(feature_table([
    ("Fund Entries", "Track owner fund entries (cash/bank transfer)"),
    ("PDF Report", "Generate owner fund report as PDF"),
]))
story.append(Spacer(1, 4*mm))

story.append(Paragraph("<b>8.2 Annual Fees</b>", subsection))
story.append(feature_table([
    ("Fee Tracking", "Track annual fees: Visa, Insurance, Mulkiya, Fine, Vehicle, Other"),
    ("Party Cards", "Visual party cards with progress bars showing collection percentage"),
    ("Donut Chart", "Summary donut chart showing total/paid/due at a glance"),
    ("Search & Filter", "Search parties by name, filter by Has Dues / Fully Paid"),
    ("Receipt PDF", "Generate annual fee receipt as PDF"),
    ("SOA PDF", "Generate Statement of Account as PDF"),
    ("Collapsible Register", "Collapsible fee register showing all entries"),
    ("Add Fee Entry Modal", "Modal form for adding/editing fee entries"),
]))
story.append(Spacer(1, 4*mm))

story.append(Paragraph("<b>8.3 Loans</b>", subsection))
story.append(feature_table([
    ("Loan Tracking", "Track loans given and recovered"),
    ("Party Profiles", "Visual party cards with recovery progress bars"),
    ("Donut Chart", "Summary donut chart showing given/recovered/outstanding"),
    ("Search & Filter", "Search parties, filter by Has Balance / Cleared"),
    ("Register Party", "Register new loan parties with contact details"),
    ("SOA PDF", "Generate loan Statement of Account as PDF"),
]))
story.append(Spacer(1, 4*mm))

story.append(Paragraph("<b>8.4 Bank Transactions</b>", subsection))
story.append(feature_table([
    ("Transaction Tracking", "Record deposits, withdrawals, and transfers"),
    ("Cheque Management", "Track cheque payments and status"),
    ("ATM Report", "ATM transaction report as PDF"),
]))
story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════════
# 9. REPORTS & PDF
# ═══════════════════════════════════════════════════════════════════
story.append(Paragraph("9. Reports & PDF Generation", section_title))
story.append(hr())
story.append(Paragraph("Over 25 built-in PDF report generators covering every aspect of the business.", body))
story.append(Spacer(1, 4*mm))

story.append(feature_table([
    ("Salary Slip PDF", "Individual salary slip with deduction breakdown"),
    ("Salary Card PDF", "Compact salary card format for WhatsApp sharing"),
    ("Kata PDF", "Driver advance/deduction statement"),
    ("Owner Fund PDF", "Owner fund entry report"),
    ("Timesheet PDF", "Driver work timesheet"),
    ("Fuel Report PDF", "Fuel purchase report with date/vehicle filters"),
    ("Field Staff Vehicle Report", "Vehicle-wise field staff activity report"),
    ("Staff Advances PDF", "Staff advance tracking report"),
    ("Staff Jobs PDF", "Maintenance jobs report per staff"),
    ("Employee List PDF", "Complete employee roster"),
    ("ATM Report PDF", "ATM transaction report"),
    ("Tax Invoice PDF", "Tax invoice with VAT"),
    ("LPO PDF", "Local Purchase Order document"),
    ("Quotation PDF", "Customer quotation with line items"),
    ("Payment Voucher PDF", "Supplier payment voucher"),
    ("Supplier SOA PDF", "Statement of Account for suppliers"),
    ("Cash Supplier Kata", "Cash supplier kata statement"),
    ("Partnership Statement", "Partnership expense split statement"),
    ("Annual Fee Receipt", "Annual fee receipt"),
    ("Annual Fee SOA", "Annual fee Statement of Account"),
    ("Loan SOA", "Loan Statement of Account"),
    ("Deduction Statement", "Detailed deduction statement per employee"),
]))
story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════════
# 10. AI ASSISTANT
# ═══════════════════════════════════════════════════════════════════
story.append(Paragraph("10. AI Assistant", section_title))
story.append(hr())
story.append(Paragraph("Built-in AI assistant powered by Google Gemini for natural language database queries.", body))
story.append(Spacer(1, 4*mm))

story.append(feature_table([
    ("Natural Language Queries", "Ask questions in plain English and get instant answers from the database"),
    ("Chat Widget", "Floating chat widget accessible from any page"),
    ("Example Queries", "\"How many active vehicles?\", \"Show pending salaries\", \"List all drivers\""),
    ("Smart SQL Generation", "AI automatically converts your question to SQL and returns results"),
]))
story.append(Spacer(1, 6*mm))

story.append(module_box("Example Questions You Can Ask", [
    "How many vehicles are currently active?",
    "Show me all employees in the Driver department",
    "What is the total outstanding salary?",
    "List all suppliers with their balances",
    "Which vehicles have expiring Mulkiya?",
    "Show me all fuel entries for this month",
    "What is the total receivable from customers?",
], GREEN))
story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════════
# 11. BACKUP & SECURITY
# ═══════════════════════════════════════════════════════════════════
story.append(Paragraph("11. Backup & Security", section_title))
story.append(hr())
story.append(Paragraph("Automated backup system with multiple tiers and PC mirror sync.", body))
story.append(Spacer(1, 4*mm))

story.append(feature_table([
    ("Daily Backup", "Automatic daily database backup (keeps last 7 days)"),
    ("Weekly Backup", "Full ZIP backup including generated files (keeps last 4 weeks)"),
    ("Monthly Backup", "Full ZIP backup with metadata (keeps last 12 months)"),
    ("PC Mirror Sync", "Nightly end-of-day copy with fresh database snapshot for backup PC"),
    ("Supplier Data Backup", "Per-supplier JSON + CSV backup in ZIP archive"),
    ("Backup Status", "View disk space, latest backups, and mirror sync status"),
    ("Auto PDF Generation", "Auto-generate supplier statement PDFs after key actions"),
]))
story.append(Spacer(1, 6*mm))

story.append(module_box("Security Features", [
    "CSRF protection on all forms",
    "Rate limiting on login attempts",
    "Role-based access control (Admin, Field Staff, Supplier, Technician)",
    "Password-protected portals",
    "Audit logging for critical actions",
    "Session management with automatic timeout",
], ORANGE))
story.append(Spacer(1, 10*mm))

# ── FOOTER ──────────────────────────────────────────────────────
story.append(hr())
story.append(Paragraph("Current Link General Contracting — ERP System v1.0", ParagraphStyle("footer", parent=small, alignment=TA_CENTER)))
story.append(Paragraph(f"Generated: {datetime.now().strftime('%d %B %Y %H:%M')}  •  www.currentlinkgc.com", ParagraphStyle("footer2", parent=small, alignment=TA_CENTER, textColor=GRAY)))

# ── BUILD ───────────────────────────────────────────────────────
doc.build(story)
print(f"PDF generated: {OUTPUT}")
print(f"Size: {os.path.getsize(OUTPUT) / 1024:.1f} KB")
