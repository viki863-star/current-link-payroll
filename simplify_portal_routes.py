#!/usr/bin/env python3
"""
Script to add simplified portal routes to app/routes.py
Run this script to add the new simplified portal functionality.
"""

import os
import re

ROUTES_FILE = "app/routes.py"

# The new routes to add after the existing supplier_portal function
NEW_ROUTES = '''
    @app.route("/portal/supplier/simple", methods=["GET"])
    @_login_required("supplier")
    def supplier_portal_simple():
        """Simplified supplier portal with only 3 forms"""
        db = open_db()
        party_code = _current_supplier_party_code()
        party = _fetch_supplier_party(db, party_code)
        
        if party is None:
            session.clear()
            flash("Supplier not found.", "error")
            return redirect(url_for("supplier_login"))
        
        # Get basic stats
        trip_count = db.execute(
            "SELECT COUNT(*) FROM cash_supplier_trips WHERE party_code = ?",
            (party_code,)
        ).fetchone()[0] or 0
        
        debit_count = db.execute(
            "SELECT COUNT(*) FROM cash_supplier_debits WHERE party_code = ?",
            (party_code,)
        ).fetchone()[0] or 0
        
        payment_count = db.execute(
            "SELECT COUNT(*) FROM cash_supplier_payments WHERE party_code = ?",
            (party_code,)
        ).fetchone()[0] or 0
        
        vehicle_count = db.execute(
            "SELECT COUNT(*) FROM supplier_assets WHERE party_code = ? AND asset_type = 'Vehicle'",
            (party_code,)
        ).fetchone()[0] or 0
        
        # Get recent activities
        recent_activities = []
        
        # Get recent trips
        trips = db.execute("""
            SELECT trip_date, amount, description, reference_no, pdf_path
            FROM cash_supplier_trips 
            WHERE party_code = ?
            ORDER BY trip_date DESC LIMIT 5
        """, (party_code,)).fetchall()
        
        for trip in trips:
            recent_activities.append({
                'date': trip['trip_date'],
                'type': 'Earning',
                'description': trip['description'] or f"Trip {trip['reference_no'] or ''}",
                'amount': trip['amount'],
                'pdf_path': trip['pdf_path']
            })
        
        # Get recent debits
        debits = db.execute("""
            SELECT entry_date, amount, category, description, pdf_path
            FROM cash_supplier_debits 
            WHERE party_code = ?
            ORDER BY entry_date DESC LIMIT 5
        """, (party_code,)).fetchall()
        
        for debit in debits:
            recent_activities.append({
                'date': debit['entry_date'],
                'type': 'Debit',
                'description': f"{debit['category']}: {debit['description'] or ''}",
                'amount': debit['amount'],
                'pdf_path': debit['pdf_path']
            })
        
        # Get recent payments
        payments = db.execute("""
            SELECT payment_date, amount, payment_method, reference_no, pdf_path
            FROM cash_supplier_payments 
            WHERE party_code = ?
            ORDER BY payment_date DESC LIMIT 5
        """, (party_code,)).fetchall()
        
        for payment in payments:
            recent_activities.append({
                'date': payment['payment_date'],
                'type': 'Payment',
                'description': f"{payment['payment_method']}: {payment['reference_no'] or ''}",
                'amount': payment['amount'],
                'pdf_path': payment['pdf_path']
            })
        
        # Sort by date
        recent_activities.sort(key=lambda x: x['date'], reverse=True)
        recent_activities = recent_activities[:10]
        
        # Get statement summary
        statement_summary = {
            'all_submitted': db.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM cash_supplier_trips WHERE party_code = ?",
                (party_code,)
            ).fetchone()[0] or 0,
            'total_paid': db.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM cash_supplier_payments WHERE party_code = ?",
                (party_code,)
            ).fetchone()[0] or 0,
            'approved_outstanding': db.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM cash_supplier_trips WHERE party_code = ?",
                (party_code,)
            ).fetchone()[0] or 0 - db.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM cash_supplier_payments WHERE party_code = ?",
                (party_code,)
            ).fetchone()[0] or 0
        }
        
        return render_template(
            "supplier_portal_simple.html",
            party=party,
            trip_count=trip_count,
            debit_count=debit_count,
            payment_count=payment_count,
            vehicle_count=vehicle_count,
            recent_activities=recent_activities,
            statement_summary=statement_summary,
            today=datetime.date.today().isoformat()
        )

    @app.route("/portal/supplier/add-earning", methods=["POST"])
    @_login_required("supplier")
    def add_supplier_earning():
        """Add a new trip earning and generate PDF"""
        db = open_db()
        party_code = _current_supplier_party_code()
        
        try:
            trip_date = request.form.get("trip_date")
            amount = float(request.form.get("amount", 0))
            description = request.form.get("description", "")
            reference_no = request.form.get("reference_no", "")
            
            # Generate PDF
            pdf_filename = f"earning_{party_code}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            pdf_path = os.path.join("D:/CashSupplierPDFs", pdf_filename)
            
            # Create directory if not exists
            os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
            
            # Simple PDF generation (you can enhance this)
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas
            
            c = canvas.Canvas(pdf_path, pagesize=letter)
            c.drawString(100, 750, f"Earning Receipt - {party_code}")
            c.drawString(100, 730, f"Date: {trip_date}")
            c.drawString(100, 710, f"Amount: AED {amount:.2f}")
            c.drawString(100, 690, f"Description: {description}")
            c.drawString(100, 670, f"Reference: {reference_no}")
            c.drawString(100, 650, f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            c.save()
            
            # Save to database
            db.execute("""
                INSERT INTO cash_supplier_trips 
                (party_code, trip_date, amount, description, reference_no, pdf_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (party_code, trip_date, amount, description, reference_no, pdf_path))
            db.commit()
            
            flash(f"Earning added successfully! PDF saved to {pdf_path}", "success")
            return redirect(url_for("supplier_portal_simple"))
            
        except Exception as e:
            flash(f"Error adding earning: {str(e)}", "error")
            return redirect(url_for("supplier_portal_simple"))

    @app.route("/portal/supplier/add-debit", methods=["POST"])
    @_login_required("supplier")
    def add_supplier_debit():
        """Add a new debit entry and generate PDF"""
        db = open_db()
        party_code = _current_supplier_party_code()
        
        try:
            debit_date = request.form.get("debit_date")
            amount = float(request.form.get("amount", 0))
            category = request.form.get("category", "")
            description = request.form.get("description", "")
            
            # Generate PDF
            pdf_filename = f"debit_{party_code}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            pdf_path = os.path.join("D:/CashSupplierPDFs", pdf_filename)
            
            # Create directory if not exists
            os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
            
            # Simple PDF generation
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas
            
            c = canvas.Canvas(pdf_path, pagesize=letter)
            c.drawString(100, 750, f"Debit Receipt - {party_code}")
            c.drawString(100, 730, f"Date: {debit_date}")
            c.drawString(100, 710, f"Amount: AED {amount:.2f}")
            c.drawString(100, 690, f"Category: {category}")
            c.drawString(100, 670, f"Description: {description}")
            c.drawString(100, 650, f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            c.save()
            
            # Save to database
            db.execute("""
                INSERT INTO cash_supplier_debits 
                (party_code, entry_date, amount, category, description, pdf_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (party_code, debit_date, amount, category, description, pdf_path))
            db.commit()
            
            flash(f"Debit added successfully! PDF saved to {pdf_path}", "success")
            return redirect(url_for("supplier_portal_simple"))
            
        except Exception as e:
            flash(f"Error adding debit: {str(e)}", "error")
            return redirect(url_for("supplier_portal_simple"))

    @app.route("/portal/supplier/add-payment", methods=["POST"])
    @_login_required("supplier")
    def add_supplier_payment():
        """Add a new payment and generate PDF"""
        db = open_db()
        party_code = _current_supplier_party_code()
        
        try:
            payment_date = request.form.get("payment_date")
            amount = float(request.form.get("amount", 0))
            payment_method = request.form.get("payment_method", "")
            reference_no = request.form.get("reference_no", "")
            notes = request.form.get("notes", "")
            
            # Generate PDF
            pdf_filename = f"payment_{party_code}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            pdf_path = os.path.join("D:/CashSupplierPDFs", pdf_filename)
            
            # Create directory if not exists
            os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
            
            # Simple PDF generation
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas
            
            c = canvas.Canvas(pdf_path, pagesize=letter)
            c.drawString(100, 750, f"Payment Receipt - {party_code}")
            c.drawString(100, 730, f"Date: {payment_date}")
            c.drawString(100, 710, f"Amount: AED {amount:.2f}")
            c.drawString(100, 690, f"Method: {payment_method}")
            c.drawString(100, 670, f"Reference: {reference_no}")
            c.drawString(100, 650, f"Notes: {notes}")
            c.drawString(100, 630, f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            c.save()
            
            # Save to database
            db.execute("""
                INSERT INTO cash_supplier_payments 
                (party_code, payment_date, amount, payment_method, reference_no, notes, pdf_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (party_code, payment_date, amount, payment_method, reference_no, notes, pdf_path))
            db.commit()
            
            flash(f"Payment added successfully! PDF saved to {pdf_path}", "success")
            return redirect(url_for("supplier_portal_simple"))
            
        except Exception as e:
            flash(f"Error adding payment: {str(e)}", "error")
            return redirect(url_for("supplier_portal_simple"))
'''

def add_routes_to_file():
    """Add the new routes to routes.py"""
    with open(ROUTES_FILE, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find where to insert - after the supplier_portal function
    # Look for the end of supplier_portal function (after the return statement)
    pattern = r'(\s+return render_template\s*\([^)]+\)\s*\n\s+\))'
    
    # Find the supplier_portal function
    supplier_portal_start = content.find('def supplier_portal():')
    if supplier_portal_start == -1:
        print("Error: Could not find supplier_portal function")
        return False
    
    # Find the end of the function (look for empty line after return)
    search_from = supplier_portal_start
    function_end = -1
    
    # Look for a line with only whitespace after a return statement
    lines = content[search_from:].split('\n')
    brace_count = 0
    in_function = False
    
    for i, line in enumerate(lines):
        if 'def supplier_portal():' in line:
            in_function = True
            brace_count = 1
        elif in_function:
            brace_count += line.count('    ') // 4  # Simple indentation detection
            if brace_count == 0 and line.strip() == '':
                function_end = search_from + sum(len(l) + 1 for l in lines[:i+1])
                break
    
    if function_end == -1:
        # Fallback: insert after the supplier_portal route decorator
        function_end = content.find('@app.route', supplier_portal_start + 1)
        function_end = content.find('\n\n', function_end)
    
    if function_end == -1:
        print("Error: Could not find where to insert new routes")
        return False
    
    # Insert the new routes
    new_content = content[:function_end] + '\n' + NEW_ROUTES + content[function_end:]
    
    # Write back
    with open(ROUTES_FILE, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print("Successfully added simplified portal routes to routes.py")
    print("New routes added:")
    print("1. /portal/supplier/simple - Simplified portal view")
    print("2. /portal/supplier/add-earning - Add earning with PDF")
    print("3. /portal/supplier/add-debit - Add debit with PDF")
    print("4. /portal/supplier/add-payment - Add payment with PDF")
    print("\nNote: You need to install reportlab for PDF generation:")
    print("pip install reportlab")
    
    return True

if __name__ == "__main__":
    print("Adding simplified portal routes...")
    if add_routes_to_file():
        print("\n✅ Routes added successfully!")
        print("\nNext steps:")
        print("1. Install reportlab: pip install reportlab")
        print("2. Create D:/CashSupplierPDFs directory")
        print("3. Restart the Flask application")
        print("4. Access simplified portal at: /portal/supplier/simple")
    else:
        print("❌ Failed to add routes")