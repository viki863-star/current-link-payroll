from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, Image, PageBreak, KeepTogether, HRFlowable)
from reportlab.lib.colors import HexColor, white, black
from reportlab.pdfgen import canvas as cv
from PyPDF2 import PdfMerger
import os, tempfile

W, H = A4
CW = 210*mm - 24*mm
OUT = os.path.join(os.environ['USERPROFILE'], "Desktop", "Current_Link_Company_Profile_v2.pdf")
STATIC = r"C:\Users\user\current-link-payroll\app\static"
TEMP = os.path.join(tempfile.gettempdir(), "profile_inner.pdf")

def S(name, **kw):
    kw.setdefault("fontSize", 10)
    kw.setdefault("leading", 14)
    kw.setdefault("textColor", HexColor("#334155"))
    kw.setdefault("fontName", "Helvetica")
    return ParagraphStyle(name, **kw)

# ═══════════════════════════════════════════════════
# BUILD INNER PAGES (with margins)
# ═══════════════════════════════════════════════════
doc = SimpleDocTemplate(TEMP, pagesize=A4, leftMargin=12*mm, rightMargin=12*mm,
                         topMargin=10*mm, bottomMargin=14*mm)
els = []

# ─── PAGE 1: ABOUT US ───
els.append(Spacer(1, 8*mm))
els.append(Paragraph("<font color='#F59E0B' size='10'>01</font>  <font color='#94A3B8' size='10'>// ABOUT US</font>", S("_sec", fontSize=10, textColor=HexColor("#94A3B8"))))
els.append(Paragraph("Who We Are", S("_h1", fontSize=28, fontName="Helvetica-Bold", textColor=HexColor("#0F172A"), leading=34)))
els.append(Spacer(1, 2*mm))
els.append(HRFlowable(width="30%", thickness=1.5, color=HexColor("#F59E0B")))
els.append(Spacer(1, 6*mm))

intro_data = [[
    Paragraph("""<b>Current Link Transport &amp; General Contracting LLC SPC</b> is a premier heavy equipment and transport solutions provider based in Mussaffah, <b>Abu Dhabi</b>. Since our establishment in <b>2015</b>, we have grown into a trusted partner for major contractors, government entities, and industrial clients across the <b>United Arab Emirates</b>.<br/><br/>We specialize in <b>water supply, water removal, and heavy equipment hire</b> including excavators, cranes, man lifts, trailers, forklifts, bobcats, and graders. All equipment is provided with <b>experienced, trained operators</b> on monthly rental basis to leading companies across the UAE.<br/><br/>Our company is built on the principles of <b>reliability, safety, and excellence</b>. Over a decade of experience has given us deep understanding of the UAE's construction and industrial sectors.""",
    S("_intro", fontSize=10.5, textColor=HexColor("#475569"), alignment=TA_JUSTIFY, leading=16)),
]]
intro_t = Table(intro_data, colWidths=[CW])
intro_t.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
els.append(intro_t)
els.append(Spacer(1, 8*mm))

# Stats row
cw_s = (CW - 12*mm) / 4
stats = [
    ("10+", "Years of<br/>Experience", HexColor("#2563EB")),
    ("50+", "Equipment<br/>Fleet", HexColor("#059669")),
    ("100+", "Projects<br/>Completed", HexColor("#D97706")),
    ("24/7", "Operations<br/>Support", HexColor("#DC2626")),
]
stat_cells = []
for num, label, color in stats:
    cell = [[
        Paragraph(f"<font size='26' color='{color.hexval()}'><b>{num}</b></font>", S("_sn", fontSize=26, fontName="Helvetica-Bold", textColor=color, alignment=TA_CENTER, leading=30)),
        Paragraph(label, S("_sl", fontSize=8, textColor=HexColor("#64748B"), alignment=TA_CENTER, leading=11)),
    ]]
    ct = Table(cell, colWidths=[cw_s])
    ct.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("BOX",(0,0),(-1,-1),0.5, HexColor("#E2E8F0")),
        ("TOPPADDING",(0,0),(-1,-1),8), ("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("BACKGROUND",(0,0),(-1,-1), HexColor("#F8FAFC")),
    ]))
    stat_cells.append(ct)

stat_row = Table([stat_cells], colWidths=[cw_s]*4)
stat_row.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),3),("RIGHTPADDING",(0,0),(-1,-1),3)]))
els.append(stat_row)
els.append(Spacer(1, 8*mm))

loc_data = [[
    Paragraph("<b>Our Location</b>", S("_lh", fontSize=12, fontName="Helvetica-Bold", textColor=HexColor("#0F172A"), leading=15)),
    Paragraph("Confident Property Management Building, Behind Aramex, First Floor, B-Block - Office 102, M9, Mussaffah \u2014 Abu Dhabi, UAE", S("_ld", fontSize=9.5, textColor=HexColor("#475569"), leading=14)),
]]
loc_t = Table(loc_data, colWidths=[35*mm, CW-35*mm])
loc_t.setStyle(TableStyle([
    ("VALIGN",(0,0),(-1,-1),"TOP"),
    ("LEFTPADDING",(0,0),(-1,-1),4), ("RIGHTPADDING",(0,0),(-1,-1),4),
    ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
    ("BACKGROUND",(0,0),(-1,-1), HexColor("#EFF6FF")),
    ("BOX",(0,0),(-1,-1),0.5, HexColor("#BFDBFE")),
]))
els.append(loc_t)
els.append(Spacer(1, 4*mm))
els.append(Paragraph("Licensed SPC Company \u2014 Fully licensed by the Abu Dhabi Department of Economic Development", S("_lic", fontSize=9.5, textColor=HexColor("#475569"), leading=13)))

# ─── PAGE 2: OUR SERVICES ───
els.append(PageBreak())
els.append(Spacer(1, 8*mm))
els.append(Paragraph("<font color='#F59E0B' size='10'>02</font>  <font color='#94A3B8' size='10'>// OUR SERVICES</font>", S("_sec", fontSize=10, textColor=HexColor("#94A3B8"))))
els.append(Paragraph("Equipment &amp; Transport Solutions", S("_h1", fontSize=26, fontName="Helvetica-Bold", textColor=HexColor("#0F172A"), leading=32)))
els.append(Spacer(1, 2*mm))
els.append(HRFlowable(width="30%", thickness=1.5, color=HexColor("#F59E0B")))
els.append(Spacer(1, 6*mm))

services = [
    ("EXCAVATOR.png", "EXCAVATOR", "Heavy-duty excavation for construction, demolition, and site preparation. Equipped with experienced operators for maximum productivity."),
    ("CRANE CARD.png", "CRANE", "Mobile crane services for lifting, installation, and industrial project support. Available in various capacities."),
    ("MAN LIFT.png", "MAN LIFT", "Boom lifts and aerial platforms for high-reach maintenance and construction work. Safe and reliable access."),
    ("TRAILER CARD.png", "TRAILER", "Low-bed and flatbed trailers with driver for monthly rental \u2014 ideal for major contractors and government projects."),
    ("FORKLIFT CARD.png", "FORKLIFT", "Warehouse and construction forklifts for material handling and loading operations. Efficient logistics solutions."),
    ("BOBCAT  SKID STEER.png", "BOBCAT / SKID STEER", "Compact loaders for grading, digging, and site clean-up in tight spaces. Versatile and maneuverable."),
    ("GRADER.png", "GRADER", "Precision grading for road construction, land leveling, and infrastructure projects. High-accuracy results."),
    ("WATER TANKER.png", "WATER TANKER", "Water supply and removal services for construction sites, industrial facilities, and remote locations across the UAE."),
]

for i, (img_file, title, desc) in enumerate(services):
    row_items = []
    # Equipment image
    try:
        img_path = os.path.join(STATIC, img_file)
        if os.path.exists(img_path):
            eq_img = Image(img_path, width=55*mm, height=30*mm)
        else:
            eq_img = Paragraph("", S("_emp", fontSize=6))
    except:
        eq_img = Paragraph("", S("_emp", fontSize=6))
    svc_data = [
        [eq_img],
        [Paragraph(f"<b>{title}</b>", S("_st", fontSize=10, fontName="Helvetica-Bold", textColor=HexColor("#0F172A"), alignment=TA_CENTER, leading=13))],
        [Paragraph(desc, S("_sd", fontSize=7.5, textColor=HexColor("#64748B"), alignment=TA_CENTER, leading=10))],
    ]
    svc_tbl = Table(svc_data, colWidths=[(CW-10*mm)/2])
    svc_tbl.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("LEFTPADDING",(0,0),(-1,-1),4), ("RIGHTPADDING",(0,0),(-1,-1),4),
        ("TOPPADDING",(0,0),(-1,-1),6), ("BOTTOMPADDING",(0,0),(-1,-1),6),
        ("BOX",(0,0),(-1,-1),0.5, HexColor("#E2E8F0")),
        ("BACKGROUND",(0,0),(-1,-1), HexColor("#FAFAFA") if i % 2 == 0 else white),
    ]))
    row_items.append(svc_tbl)
    if i % 2 == 1 or i == len(services) - 1:
        # Check if we need a filler
        if len(row_items) == 1 and i == len(services) - 1 and i % 2 == 0:
            filler = Paragraph("", S("_emp", fontSize=6))
            row_items.append(filler)
        row_tbl = Table([row_items], colWidths=[(CW-10*mm)/2]*len(row_items))
        row_tbl.setStyle(TableStyle([
            ("VALIGN",(0,0),(-1,-1),"TOP"),
            ("LEFTPADDING",(0,0),(-1,-1),5), ("RIGHTPADDING",(0,0),(-1,-1),5),
        ]))
        els.append(row_tbl)
        els.append(Spacer(1, 3*mm))

els.append(Spacer(1, 6*mm))
els.append(Paragraph("<i>All equipment provided with experienced operators, insurance, and 24/7 support on monthly rental basis.</i>", S("_note", fontSize=9, textColor=HexColor("#94A3B8"), alignment=TA_CENTER, leading=12)))

# ─── PAGE 3: FLEET ───
els.append(PageBreak())
els.append(Spacer(1, 8*mm))
els.append(Paragraph("<font color='#F59E0B' size='10'>03</font>  <font color='#94A3B8' size='10'>// OUR FLEET</font>", S("_sec", fontSize=10, textColor=HexColor("#94A3B8"))))
els.append(Paragraph("50+ Well-Maintained Equipment Units", S("_h1", fontSize=26, fontName="Helvetica-Bold", textColor=HexColor("#0F172A"), leading=32)))
els.append(Spacer(1, 2*mm))
els.append(HRFlowable(width="30%", thickness=1.5, color=HexColor("#F59E0B")))
els.append(Spacer(1, 6*mm))
els.append(Paragraph("Our fleet comprises over <b>50 well-maintained units</b> available for monthly rental across the UAE. Every piece of equipment is regularly serviced, fully insured, and operated by trained professionals with <b>8+ years of UAE experience</b>.", S("_fi", fontSize=10.5, textColor=HexColor("#475569"), alignment=TA_JUSTIFY, leading=15)))
els.append(Spacer(1, 6*mm))

fh = ParagraphStyle("_fh", fontSize=8, fontName="Helvetica-Bold", textColor=white, alignment=TA_CENTER, leading=11)
fc = ParagraphStyle("_fc", fontSize=8.5, textColor=HexColor("#334155"), alignment=TA_CENTER, leading=11)
fcl = ParagraphStyle("_fcl", fontSize=8.5, textColor=HexColor("#334155"), alignment=TA_LEFT, leading=11)

fleet_rows = [
    [Paragraph("Equipment Type", fh), Paragraph("Units", fh), Paragraph("Capacity Range", fh), Paragraph("Application", fh)],
    [Paragraph("Excavator", fcl), Paragraph("10+", fc), Paragraph("20\u201350 Ton", fc), Paragraph("Construction, Demolition", fc)],
    [Paragraph("Crane", fcl), Paragraph("8", fc), Paragraph("25\u2013100 Ton", fc), Paragraph("Lifting, Installation", fc)],
    [Paragraph("Man Lift", fcl), Paragraph("6", fc), Paragraph("12\u201340m", fc), Paragraph("High-reach Maintenance", fc)],
    [Paragraph("Trailer", fcl), Paragraph("10", fc), Paragraph("20\u201360 Ton", fc), Paragraph("Equipment Transport", fc)],
    [Paragraph("Forklift", fcl), Paragraph("6", fc), Paragraph("3\u201325 Ton", fc), Paragraph("Material Handling", fc)],
    [Paragraph("Bobcat / Skid Steer", fcl), Paragraph("4", fc), Paragraph("Various", fc), Paragraph("Grading, Clean-up", fc)],
    [Paragraph("Grader", fcl), Paragraph("4", fc), Paragraph("Various", fc), Paragraph("Road Construction", fc)],
    [Paragraph("Water Tanker", fcl), Paragraph("6", fc), Paragraph("5,000\u201312,000 Gal", fc), Paragraph("Water Supply/Removal", fc)],
]
ft = Table(fleet_rows, colWidths=[48*mm, 24*mm, 32*mm, CW-112*mm])
ft.setStyle(TableStyle([
    ("BACKGROUND", (0,0), (-1,0), HexColor("#1E3A5F")),
    ("TEXTCOLOR", (0,0), (-1,0), white),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6),
    ("TOPPADDING",(0,0),(-1,-1),5), ("BOTTOMPADDING",(0,0),(-1,-1),5),
    ("GRID",(0,0),(-1,-1),0.5, HexColor("#E2E8F0")),
    ("ROWBACKGROUNDS", (0,1), (-1,-1), [white, HexColor("#F8FAFC")]),
]))
els.append(ft)
els.append(Spacer(1, 10*mm))

highlights = [
    "All equipment provided with experienced, trained operators",
    "Monthly rental basis \u2014 flexible terms for long-term projects",
    "Regular maintenance and service \u2014 minimizing downtime",
    "Full insurance coverage on all units",
    "24/7 emergency support and breakdown assistance",
]
for h in highlights:
    els.append(Paragraph("\u2713  " + h, S("_hl", fontSize=9.5, textColor=HexColor("#475569"), leading=14)))

# ─── PAGE 4: WHY CHOOSE US ───
els.append(PageBreak())
els.append(Spacer(1, 8*mm))
els.append(Paragraph("<font color='#F59E0B' size='10'>04</font>  <font color='#94A3B8' size='10'>// WHY CHOOSE US</font>", S("_sec", fontSize=10, textColor=HexColor("#94A3B8"))))
els.append(Paragraph("What Sets Us Apart", S("_h1", fontSize=26, fontName="Helvetica-Bold", textColor=HexColor("#0F172A"), leading=32)))
els.append(Spacer(1, 2*mm))
els.append(HRFlowable(width="30%", thickness=1.5, color=HexColor("#F59E0B")))
els.append(Spacer(1, 8*mm))

reasons = [
    ("01", "Safety First", "We maintain rigorous HSE (Health, Safety & Environment) protocols across all operations. Every project follows strict safety guidelines to protect our team, our clients, and the communities we serve. Safety is not just a policy \u2014 it is our culture.", HexColor("#2563EB")),
    ("02", "Experienced Operators", "Our team has 8+ years of UAE experience. Every operator is trained, licensed, and familiar with local site conditions, regulations, and best practices.", HexColor("#059669")),
    ("03", "Modern & Reliable Fleet", "All equipment is regularly maintained and serviced at authorized workshops. We invest in modern, reliable machinery to minimize downtime and maximize productivity.", HexColor("#D97706")),
    ("04", "24/7 Operations Support", "Our operations never stop. We provide round-the-clock support for emergency requirements, breakdowns, and urgent project needs.", HexColor("#DC2626")),
    ("05", "Abu Dhabi Based", "Strategically located in Mussaffah \u2014 the industrial heart of Abu Dhabi. Quick mobilization across the UAE ensuring timely delivery and cost-effective logistics.", HexColor("#7C3AED")),
    ("06", "Proven Track Record", "10+ years of service to leading companies including NMDC, Al Jaber, Khidmah, Tadweer, Tabreed, and many more. Our reputation is built on consistent delivery and client satisfaction.", HexColor("#0891B2")),
]

for i, (num, title, desc, color) in enumerate(reasons):
    els.append(Spacer(1, 2*mm))
    r_data = [[
        Paragraph(f"<font color='{color.hexval()}' size='22'><b>{num}</b></font>", S("_rn", fontSize=22, fontName="Helvetica-Bold", textColor=color, alignment=TA_LEFT)),
        Paragraph(f"<font size='12'><b>{title}</b></font>", S("_rt", fontSize=12, fontName="Helvetica-Bold", textColor=HexColor("#0F172A"), alignment=TA_LEFT, leading=15)),
        Paragraph(desc, S("_rd", fontSize=9, textColor=HexColor("#475569"), alignment=TA_JUSTIFY, leading=12.5)),
    ]]
    rt = Table(r_data, colWidths=[14*mm, 50*mm, CW-72*mm])
    rt.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LEFTPADDING",(0,0),(-1,-1),4), ("RIGHTPADDING",(0,0),(-1,-1),4),
        ("TOPPADDING",(0,0),(-1,-1),6), ("BOTTOMPADDING",(0,0),(-1,-1),6),
        ("BACKGROUND",(0,0),(-1,-1), HexColor("#FAFAFA") if i % 2 == 0 else white),
        ("BOX",(0,0),(-1,-1),0.5, HexColor("#E2E8F0")),
        ("LINELEFT",(0,0),(0,-1),3, color),
    ]))
    els.append(rt)

# ─── PAGE 5: CLIENTS ───
els.append(PageBreak())
els.append(Spacer(1, 8*mm))
els.append(Paragraph("<font color='#F59E0B' size='10'>05</font>  <font color='#94A3B8' size='10'>// OUR CLIENTS</font>", S("_sec", fontSize=10, textColor=HexColor("#94A3B8"))))
els.append(Paragraph("Trusted by Industry Leaders", S("_h1", fontSize=26, fontName="Helvetica-Bold", textColor=HexColor("#0F172A"), leading=32)))
els.append(Spacer(1, 2*mm))
els.append(HRFlowable(width="30%", thickness=1.5, color=HexColor("#F59E0B")))
els.append(Spacer(1, 6*mm))
els.append(Paragraph("We are proud to have served some of the most respected names in the UAE's construction, energy, and infrastructure sectors. Our commitment to quality and reliability has earned us the trust of industry leaders across the region.", S("_cli", fontSize=10, textColor=HexColor("#475569"), alignment=TA_JUSTIFY, leading=14)))
els.append(Spacer(1, 8*mm))

client_files = [
    ("NMDC D&M.png", "NMDC D&M", "Energy & Marine"),
    ("gcc logo.jpg", "GCC", "Construction"),
    ("Al jaber.jpg", "Al Jaber", "Building & Infrastructure"),
    ("norul.png", "Norul", "Logistics & Transport"),
    ("khidmah.png", "Khidmah", "Facilities Management"),
    ("tadweer.png", "Tadweer", "Waste Management"),
    ("Tabreed-logo.jpg", "Tabreed", "District Cooling"),
    ("WBG.jpg", "WBG", "General Contracting"),
    ("cleanco.jpg", "Cleanco", "Cleaning Services"),
]

from itertools import chain
# 3 per row
for row_start in range(0, len(client_files), 3):
    row_cells = []
    for j in range(3):
        if row_start + j < len(client_files):
            fname, cname, sector = client_files[row_start+j]
            fpath = os.path.join(STATIC, "client", "top nine", fname)
            if not os.path.exists(fpath):
                fpath = os.path.join(STATIC, fname)
            try:
                logo_img = Image(fpath, width=38*mm, height=18*mm)
            except:
                logo_img = Paragraph(cname, S("_cln", fontSize=10, fontName="Helvetica-Bold", textColor=HexColor("#0F172A"), alignment=TA_CENTER))
            cell_data = [
                [logo_img],
                [Paragraph(f"<b>{cname}</b>", S("_cn", fontSize=8, fontName="Helvetica-Bold", textColor=HexColor("#0F172A"), alignment=TA_CENTER, leading=11))],
                [Paragraph(sector, S("_cs", fontSize=7, textColor=HexColor("#94A3B8"), alignment=TA_CENTER, leading=9))],
            ]
            ct = Table(cell_data, colWidths=[(CW-16*mm)/3])
            ct.setStyle(TableStyle([
                ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
                ("ALIGN",(0,0),(-1,-1),"CENTER"),
                ("BOX",(0,0),(-1,-1),0.5, HexColor("#E2E8F0")),
                ("TOPPADDING",(0,0),(-1,-1),10), ("BOTTOMPADDING",(0,0),(-1,-1),10),
                ("BACKGROUND",(0,0),(-1,-1), white),
            ]))
            row_cells.append(ct)
        else:
            row_cells.append(Paragraph("", S("_emp", fontSize=6)))
    row_t = Table([row_cells], colWidths=[(CW-16*mm)/3]*3)
    row_t.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LEFTPADDING",(0,0),(-1,-1),4), ("RIGHTPADDING",(0,0),(-1,-1),4),
    ]))
    els.append(row_t)
    els.append(Spacer(1, 4*mm))

# ─── PAGE 6: CERTIFICATIONS ───
els.append(PageBreak())
els.append(Spacer(1, 8*mm))
els.append(Paragraph("<font color='#F59E0B' size='10'>06</font>  <font color='#94A3B8' size='10'>// CERTIFICATIONS</font>", S("_sec", fontSize=10, textColor=HexColor("#94A3B8"))))
els.append(Paragraph("Certified &amp; Compliant", S("_h1", fontSize=24, fontName="Helvetica-Bold", textColor=HexColor("#0F172A"), leading=30)))
els.append(Spacer(1, 2*mm))
els.append(HRFlowable(width="30%", thickness=1.5, color=HexColor("#F59E0B")))
els.append(Spacer(1, 6*mm))

certs = [
    ("ICV-Certificate logo.png", "ICV Certified", "In-Country Value Program \u2014 Demonstrating our commitment to local economic development, employment of UAE nationals, and investment in the local supply chain."),
    ("IOS 14001.png", "ISO 14001 Certified", "Environmental Management System \u2014 Our operations meet international standards for environmental responsibility, waste management, and sustainability."),
    ("VMS Logo.png", "VMS Certified", "Verified Management Systems \u2014 Third-party verified management processes ensuring quality, consistency, and continuous improvement."),
]

for img_file, title, desc in certs:
    els.append(Spacer(1, 3*mm))
    try:
        cert_img = Image(os.path.join(STATIC, img_file), width=16*mm, height=16*mm)
    except:
        cert_img = Paragraph("\u2713", S("_ci", fontSize=16, textColor=HexColor("#F59E0B"), alignment=TA_CENTER))
    cert_data = [[
        cert_img,
        Paragraph(f"<b>{title}</b>", S("_ct", fontSize=11, fontName="Helvetica-Bold", textColor=HexColor("#0F172A"), leading=14)),
        Paragraph(desc, S("_cd", fontSize=9, textColor=HexColor("#475569"), alignment=TA_JUSTIFY, leading=12.5)),
    ]]
    ct = Table(cert_data, colWidths=[20*mm, 45*mm, CW-73*mm])
    ct.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LEFTPADDING",(0,0),(-1,-1),8), ("RIGHTPADDING",(0,0),(-1,-1),8),
        ("TOPPADDING",(0,0),(-1,-1),10), ("BOTTOMPADDING",(0,0),(-1,-1),10),
        ("BOX",(0,0),(-1,-1),0.5, HexColor("#E2E8F0")),
        ("BACKGROUND",(0,0),(-1,-1), white),
        ("LINELEFT",(0,0),(0,-1),3, HexColor("#F59E0B")),
    ]))
    els.append(ct)

# ─── PAGE 7: CONTACT ───
els.append(PageBreak())
els.append(Spacer(1, 20*mm))
els.append(Paragraph("<font color='#F59E0B' size='10'>07</font>  <font color='#94A3B8' size='10'>// CONTACT</font>", S("_sec", fontSize=10, textColor=HexColor("#94A3B8"), alignment=TA_CENTER)))
els.append(Spacer(1, 6*mm))
els.append(Paragraph("Get In Touch", S("_h1c", fontSize=36, fontName="Helvetica-Bold", textColor=HexColor("#0F172A"), alignment=TA_CENTER, leading=42)))
els.append(Spacer(1, 4*mm))
els.append(HRFlowable(width="20%", thickness=2, color=HexColor("#F59E0B")))
els.append(Spacer(1, 12*mm))

# Stamp + Sign
try:
    stamp_img = Image(os.path.join(STATIC, "Stamp.png"), width=25*mm, height=25*mm)
    sign_img = Image(os.path.join(STATIC, "Sign (1).png"), width=25*mm, height=25*mm)
    stamp_data = [[stamp_img, sign_img]]
    stamp_t = Table(stamp_data, colWidths=[30*mm, 30*mm])
    stamp_t.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),
    ]))
    stamp_container = [[Paragraph("", S("_emp", fontSize=6)), stamp_t, Paragraph("", S("_emp", fontSize=6))]]
    stamp_container_t = Table(stamp_container, colWidths=[(CW-60*mm)/2, 60*mm, (CW-60*mm)/2])
    stamp_container_t.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
    els.append(stamp_container_t)
    els.append(Spacer(1, 2*mm))
except:
    pass

els.append(Paragraph("<b>Authorized Signatory</b>", S("_auth", fontSize=11, fontName="Helvetica-Bold", textColor=HexColor("#0F172A"), alignment=TA_CENTER, leading=14)))
els.append(Spacer(1, 12*mm))

contacts = [
    ("Address", "Confident Property Management Building\nBehind Aramex, First Floor, B-Block Office 102\nM9, Mussaffah, Abu Dhabi, UAE"),
    ("Phone", "+971 50-122-4963\n+971 50-108-2900"),
    ("Email", "info@currentlinktgc.com"),
    ("Web", "www.currentlinkgc.com"),
    ("Working Hours", "Sunday \u2013 Friday: 8:00 AM \u2013 6:00 PM\n24/7 Emergency Support"),
]

# Single contact card as a table
crows = []
for label, value in contacts:
    crows.append([
        Paragraph(f"<b>{label}</b>", S("_cl", fontSize=9, fontName="Helvetica-Bold", textColor=HexColor("#0F172A"), leading=13)),
        Paragraph(value.replace("\n", "<br/>"), S("_cv", fontSize=9, textColor=HexColor("#475569"), leading=13)),
    ])

ct_master = Table(crows, colWidths=[40*mm, CW-48*mm])
ct_master.setStyle(TableStyle([
    ("VALIGN",(0,0),(-1,-1),"TOP"),
    ("LEFTPADDING",(0,0),(-1,-1),8), ("RIGHTPADDING",(0,0),(-1,-1),8),
    ("TOPPADDING",(0,0),(-1,-1),6), ("BOTTOMPADDING",(0,0),(-1,-1),6),
    ("BOX",(0,0),(-1,-1),0.5, HexColor("#E2E8F0")),
    ("BACKGROUND",(0,0),(-1,-1), HexColor("#F8FAFC")),
    ("LINEBELOW",(0,0),(-1,-2),0.3, HexColor("#E2E8F0")),
    ("LINEBELOW",(0,1),(-1,-2),0.3, HexColor("#E2E8F0")),
    ("LINEBELOW",(0,2),(-1,-2),0.3, HexColor("#E2E8F0")),
    ("LINEBELOW",(0,3),(-1,-2),0.3, HexColor("#E2E8F0")),
]))
els.append(ct_master)

els.append(Spacer(1, 18*mm))
els.append(Paragraph("Let's Work Together", S("_end", fontSize=16, fontName="Helvetica-Bold", textColor=HexColor("#2563EB"), alignment=TA_CENTER, leading=20)))
els.append(Spacer(1, 4*mm))
els.append(Paragraph("Request a quote today \u2014 we'll respond within 1 hour", S("_end2", fontSize=10, textColor=HexColor("#94A3B8"), alignment=TA_CENTER, leading=13)))
els.append(Spacer(1, 12*mm))
els.append(Paragraph("Current Link Transport &amp; General Contracting LLC SPC", S("_cn2", fontSize=9, textColor=HexColor("#94A3B8"), alignment=TA_CENTER)))
els.append(Paragraph("Mussaffah, Abu Dhabi, United Arab Emirates", S("_cn3", fontSize=8, textColor=HexColor("#94A3B8"), alignment=TA_CENTER)))
els.append(Spacer(1, 4*mm))
els.append(Paragraph("\u00a9 2026 All Rights Reserved", S("_copy", fontSize=8, textColor=HexColor("#CBD5E1"), alignment=TA_CENTER)))

doc.build(els)

# ═══════════════════════════════════════════════════
# BUILD COVER PAGE (zero margins)
# ═══════════════════════════════════════════════════
cover_pdf = os.path.join(tempfile.gettempdir(), "profile_cover.pdf")
c = cv.Canvas(cover_pdf, pagesize=A4)

# Try hero image full-bleed
hero_path = os.path.join(STATIC, "HERO SECTION.png")
if os.path.exists(hero_path):
    c.drawImage(hero_path, 0, 0, width=210*mm, height=297*mm)
else:
    # Dark background fallback
    c.setFillColor(HexColor("#0B1120"))
    c.rect(0, 0, 210*mm, 297*mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 36)
    c.drawCentredString(105*mm, 160*mm, "CURRENT LINK")
    c.setFillColor(HexColor("#F59E0B"))
    c.setFont("Helvetica", 16)
    c.drawCentredString(105*mm, 140*mm, "COMPANY PROFILE")

c.save()

# ═══════════════════════════════════════════════════
# MERGE COVER + INNER PAGES
# ═══════════════════════════════════════════════════
merger = PdfMerger()
merger.append(cover_pdf)
merger.append(TEMP)
merger.write(OUT)
merger.close()

os.remove(TEMP)
os.remove(cover_pdf)

print(f"Company profile saved: {OUT}")
print(f"Size: {os.path.getsize(OUT)/1024:.0f} KB | Pages: 8")
