import json
import re
import os
import requests
from datetime import date
from flask import render_template, request, jsonify, current_app, session
from . import ai_bp
from ..database import open_db
from app import csrf

TABLES = [
    "employees", "drivers", "field_staff", "cash_receipts", "vehicles",
    "vehicle_assignments", "salary_store", "salary_slips", "salary_payments",
    "maintenance_jobs", "technicians", "maintenance_staff_advances",
    "maintenance_papers", "parties", "suppliers", "supplier_invoices",
    "supplier_bills", "account_invoices", "account_invoice_lines",
    "account_payments", "fuel_entries",
    "customers", "customer_invoices", "customer_invoice_items",
    "customer_payments", "customer_contracts", "customer_quotations",
    "customer_lpos", "customer_documents", "service_items",
    "customer_service_orders", "tabreed_tripsheets",
]


def _get_schema():
    """Dynamically fetch schema from the database."""
    db = open_db()
    backend = current_app.config.get("DATABASE_BACKEND", "sqlite")
    lines = []
    for table in TABLES:
        try:
            if backend == "postgres":
                cols = db.execute(
                    "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = ? ORDER BY ordinal_position",
                    (table,),
                ).fetchall()
                if cols:
                    names = [f"{c['column_name']}" for c in cols]
                    lines.append(f"{table}({', '.join(names)})")
            else:
                cols = db.execute(f"PRAGMA table_info({table})").fetchall()
                if cols:
                    names = [f"{c['name']} {c['type']}" for c in cols]
                    lines.append(f"{table}({', '.join(names)})")
        except Exception:
            pass
    return "\n".join(lines)


def _is_write_sql(sql):
    s = sql.strip().upper()
    return s.startswith("INSERT") or s.startswith("UPDATE") or s.startswith("DELETE")


def _execute_sql(sql):
    db = open_db()
    is_write = _is_write_sql(sql)
    try:
        if is_write:
            result = db.execute(sql)
            db.commit()
            if hasattr(result, "fetchone"):
                row = result.fetchone()
                if row:
                    return {"affected": "insert", "row": dict(row)}
            return {"affected": "success"}
        result = db.execute(sql).fetchall()
        return [dict(row) for row in result] if result else []
    except Exception as e:
        return {"error": str(e)}


def _call_llm(messages):
    api_key = os.getenv("AI_API_KEY") or os.getenv("GROQ_API_KEY") or ""
    api_url = os.getenv("AI_API_URL", "https://api.groq.com/openai/v1/chat/completions")
    api_model = os.getenv("AI_MODEL", "llama-3.3-70b-versatile")

    if not api_key:
        return None, "AI_API_KEY not configured. Set in .env"

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": api_model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 2048,
    }

    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=10)
        data = resp.json()
        if "choices" not in data or not data["choices"]:
            err = data.get("error", {}).get("message", str(data))
            return None, f"AI error: {err}"

        raw = data["choices"][0]["message"]["content"].strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        raw = raw.strip()

        json_match = re.search(r'\{[^{}]*"(?:sql|explanation)"[^{}]*\}', raw, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group()), None
            except json.JSONDecodeError:
                pass

        if raw.startswith("{"):
            try:
                return json.loads(raw), None
            except json.JSONDecodeError:
                pass

        prefix = re.sub(r'\{.*', '', raw, count=1).strip()
        return {"explanation": prefix or raw, "sql": ""}, None
    except Exception as e:
        return None, str(e)


@ai_bp.route("/")
def ai_dashboard():
    if session.get("current_role") != "admin":
        return render_template("login-premium.html")
    return render_template("ai_dashboard.html")


@ai_bp.route("/tripsheet_save", methods=["POST"])
@csrf.exempt
def tripsheet_save():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON required"}), 400
        cid = data.get("customer_id")
        if not cid:
            return jsonify({"error": "customer_id required"}), 400
        entry_date = (data.get("entry_date") or "").strip()
        time_in = (data.get("time_in") or "").strip()
        time_out = (data.get("time_out") or "").strip()
        total_reading = round(float(data.get("total_reading", 0) or 0), 2)
        tanker_gln = (data.get("tanker_gln") or "").strip()
        trips = float(data.get("trips", 1) or 1)
        tanker_reg = (data.get("tanker_reg") or "").strip().upper()
        notes = (data.get("notes") or "").strip()
        if not entry_date:
            return jsonify({"error": "Date required"}), 400
        db = open_db()
        backend = current_app.config.get("DATABASE_BACKEND", "sqlite")
        if not tanker_gln:
            tanker_gln = "10000 GLN"
        if backend == "postgres":
            db.execute("""CREATE TABLE IF NOT EXISTS tabreed_tripsheets (
                id SERIAL PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                entry_date TEXT NOT NULL,
                time_in TEXT,
                time_out TEXT,
                total_reading REAL DEFAULT 0,
                tanker_gln TEXT,
                trips REAL DEFAULT 1,
                tanker_reg TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (NOW())
            )""")
        else:
            db.execute("""CREATE TABLE IF NOT EXISTS tabreed_tripsheets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                entry_date TEXT NOT NULL,
                time_in TEXT,
                time_out TEXT,
                total_reading REAL DEFAULT 0,
                tanker_gln TEXT,
                trips REAL DEFAULT 1,
                tanker_reg TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""")
        bill_no = request.form.get("bill_no", "").strip() or None
        db.execute("""INSERT INTO tabreed_tripsheets
            (customer_id, entry_date, time_in, time_out, total_reading, tanker_gln, trips, tanker_reg, bill_no, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (cid, entry_date, time_in or None, time_out or None, total_reading, tanker_gln, trips, tanker_reg or None, bill_no, notes or None))
        db.commit()
        count = db.execute("SELECT COUNT(*) AS cnt FROM tabreed_tripsheets WHERE customer_id=? AND entry_date=?", (cid, entry_date)).fetchone()
        cnt = count["cnt"] if count else 0
        db.close()
        return jsonify({"success": True, "message": "Tripsheet entry saved", "customer_id": cid, "date": entry_date, "count": cnt})
    except Exception as e:
        import traceback
        current_app.logger.error("Tripsheet save error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/anomaly-detection", methods=["GET"])
def anomaly_detection():
    """AI-powered anomaly detection for expenses, attendance, and payments."""
    try:
        db = open_db()
        category = request.args.get("category", "all")  # all, expenses, attendance, payments
        
        anomalies = []
        
        # Expense Anomalies (fuel entries)
        if category in ["all", "expenses"]:
            fuel_entries = db.execute("""
                SELECT vehicle_plate, entry_date, total_amount, gallons, rate_per_gallon
                FROM fuel_entries
                WHERE entry_date >= date('now', '-90 days')
                ORDER BY entry_date DESC
                LIMIT 100
            """).fetchall()
            
            if fuel_entries:
                amounts = [float(f["total_amount"] or 0) for f in fuel_entries]
                if amounts:
                    avg = sum(amounts) / len(amounts)
                    std = (sum((x - avg) ** 2 for x in amounts) / len(amounts)) ** 0.5
                    
                    for entry in fuel_entries:
                        amount = float(entry["total_amount"] or 0)
                        if std > 0 and abs(amount - avg) > 2 * std:  # 2 standard deviations
                            anomalies.append({
                                "type": "expense",
                                "severity": "high" if abs(amount - avg) > 3 * std else "medium",
                                "description": f"Unusual fuel charge: AED {amount:.2f} for {entry['vehicle_plate']} on {entry['entry_date']}",
                                "value": amount,
                                "expected": round(avg, 2),
                                "deviation": round(((amount - avg) / avg) * 100, 1) if avg > 0 else 0
                            })
        
        # Payment Anomalies (supplier invoices)
        if category in ["all", "payments"]:
            invoices = db.execute("""
                SELECT supplier_id, invoice_date, total_amount, invoice_number
                FROM supplier_invoices
                WHERE invoice_date >= date('now', '-90 days')
                ORDER BY invoice_date DESC
                LIMIT 100
            """).fetchall()
            
            if invoices:
                amounts = [float(i["total_amount"] or 0) for i in invoices]
                if amounts:
                    avg = sum(amounts) / len(amounts)
                    std = (sum((x - avg) ** 2 for x in amounts) / len(amounts)) ** 0.5
                    
                    for invoice in invoices:
                        amount = float(invoice["total_amount"] or 0)
                        if std > 0 and abs(amount - avg) > 2 * std:
                            anomalies.append({
                                "type": "payment",
                                "severity": "high" if abs(amount - avg) > 3 * std else "medium",
                                "description": f"Unusual invoice amount: AED {amount:.2f} from supplier {invoice['supplier_id']}",
                                "value": amount,
                                "expected": round(avg, 2),
                                "deviation": round(((amount - avg) / avg) * 100, 1) if avg > 0 else 0
                            })
        
        # Attendance Anomalies (driver timesheets)
        if category in ["all", "attendance"]:
            timesheets = db.execute("""
                SELECT driver_id, entry_date, hours_worked
                FROM driver_timesheets
                WHERE entry_date >= date('now', '-90 days')
                ORDER BY entry_date DESC
                LIMIT 100
            """).fetchall()
            
            if timesheets:
                hours = [float(t["hours_worked"] or 0) for t in timesheets]
                if hours:
                    avg = sum(hours) / len(hours)
                    std = (sum((x - avg) ** 2 for x in hours) / len(hours)) ** 0.5
                    
                    for ts in timesheets:
                        hours_worked = float(ts["hours_worked"] or 0)
                        if std > 0 and abs(hours_worked - avg) > 2 * std:
                            anomalies.append({
                                "type": "attendance",
                                "severity": "high" if hours_worked > avg + 3 * std or hours_worked < avg - 3 * std else "medium",
                                "description": f"Unusual hours: {hours_worked:.1f}h for driver {ts['driver_id']} on {ts['entry_date']}",
                                "value": hours_worked,
                                "expected": round(avg, 1),
                                "deviation": round(((hours_worked - avg) / avg) * 100, 1) if avg > 0 else 0
                            })
        
        # Sort by severity and recency
        severity_order = {"high": 0, "medium": 1, "low": 2}
        anomalies.sort(key=lambda x: (severity_order.get(x["severity"], 2), -x.get("value", 0)))
        
        return jsonify({
            "anomalies": anomalies[:20],  # Return top 20
            "total": len(anomalies),
            "category": category
        })
        
    except Exception as e:
        import traceback
        current_app.logger.error("Anomaly detection error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/revenue-forecast", methods=["GET"])
def revenue_forecast():
    """AI-powered revenue forecasting from customer payments."""
    try:
        db = open_db()
        months = request.args.get("months", "3")
        
        # Get historical customer payment data
        historical = db.execute("""
            SELECT payment_date, SUM(amount) AS total_revenue, COUNT(*) AS payment_count
            FROM customer_payments
            WHERE payment_date IS NOT NULL
            GROUP BY payment_date
            ORDER BY payment_date DESC
            LIMIT 24
        """).fetchall()
        
        if not historical:
            return jsonify({
                "forecast": None,
                "message": "No historical payment data available for forecasting."
            })
        
        # Get current active customers and average payment
        current_customers = db.execute("""
            SELECT COUNT(*) AS cnt, AVG(COALESCE(credit_limit, 0)) AS avg_credit
            FROM customers
            WHERE status = 'Active'
        """).fetchone()
        
        # Prepare data for AI analysis
        data_summary = []
        for row in historical:
            data_summary.append({
                "date": row["payment_date"],
                "total_revenue": float(row["total_revenue"] or 0),
                "payment_count": row["payment_count"]
            })
        
        current_count = current_customers["cnt"] or 0
        avg_credit = float(current_customers["avg_credit"] or 0)
        
        # Use AI to forecast revenue with scenarios
        prompt = f"""
        Historical revenue data (last 24 payments):
        {json.dumps(data_summary, indent=2)}
        
        Current active customers: {current_count}
        Average credit limit: AED {avg_credit:.2f}
        
        Forecast revenue for the next {months} months with 3 scenarios:
        1. Optimistic (best case - 15% higher than expected)
        2. Base (most likely case)
        3. Pessimistic (worst case - 15% lower than expected)
        
        For each month, provide:
        - Month label (e.g., "2026-08", "2026-09")
        - Optimistic forecast
        - Base forecast
        - Pessimistic forecast
        - Trend direction
        
        Consider:
        - Historical payment patterns and seasonality
        - Current customer count and credit limits
        - Typical payment cycles
        
        Respond with JSON only: {{"forecasts": [{{"month": "YYYY-MM", "optimistic": amount, "base": amount, "pessimistic": amount, "trend": "up/down/stable"}}], "summary": "brief insight", "confidence": "high/medium/low"}}
        """
        
        result, err = _call_llm([{"role": "system", "content": "You are a financial forecasting AI. Respond with JSON only. Use realistic AED amounts."}, {"role": "user", "content": prompt}])
        
        if err:
            # Fallback to simple calculation
            base_monthly = current_count * avg_credit * 0.3  # Assume 30% of credit utilized monthly
            forecasts = []
            from datetime import datetime, timedelta
            today = datetime.now()
            for i in range(1, int(months) + 1):
                future_month = (today.replace(day=1) + timedelta(days=32*i)).replace(day=1)
                forecasts.append({
                    "month": future_month.strftime("%Y-%m"),
                    "optimistic": round(base_monthly * 1.15, 2),
                    "base": round(base_monthly, 2),
                    "pessimistic": round(base_monthly * 0.85, 2),
                    "trend": "stable"
                })
            return jsonify({
                "forecasts": forecasts,
                "summary": f"Based on {current_count} active customers with average credit AED {avg_credit:.2f}",
                "confidence": "medium",
                "historical": data_summary[:6],
                "current_customers": current_count,
                "method": "calculation"
            })
        
        if isinstance(result, dict):
            forecasts = result.get("forecasts", [])
            if not forecasts:
                base_monthly = current_count * avg_credit * 0.3
                forecasts = []
                from datetime import datetime, timedelta
                today = datetime.now()
                for i in range(1, int(months) + 1):
                    future_month = (today.replace(day=1) + timedelta(days=32*i)).replace(day=1)
                    forecasts.append({
                        "month": future_month.strftime("%Y-%m"),
                        "optimistic": round(base_monthly * 1.15, 2),
                        "base": round(base_monthly, 2),
                        "pessimistic": round(base_monthly * 0.85, 2),
                        "trend": "stable"
                    })
            return jsonify({
                "forecasts": forecasts[:int(months)],
                "summary": result.get("summary", ""),
                "confidence": result.get("confidence", "medium"),
                "historical": data_summary[:6],
                "current_customers": current_count,
                "method": "ai"
            })
        
        return jsonify({"error": "Invalid AI response"}), 500
        
    except Exception as e:
        import traceback
        current_app.logger.error("Revenue forecast error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/expense-forecast", methods=["GET"])
def expense_forecast():
    """AI-powered expense forecasting (fuel, maintenance, suppliers)."""
    try:
        db = open_db()
        months = request.args.get("months", "3")
        category = request.args.get("category", "all")  # all, fuel, maintenance, suppliers
        
        forecasts_by_category = {}
        
        # Fuel expenses
        if category in ["all", "fuel"]:
            fuel_data = db.execute("""
                SELECT entry_date, SUM(total_amount) AS total_fuel
                FROM fuel_entries
                WHERE entry_date IS NOT NULL
                GROUP BY entry_date
                ORDER BY entry_date DESC
                LIMIT 24
            """).fetchall()
            
            if fuel_data:
                fuel_summary = [{"date": f["entry_date"], "amount": float(f["total_fuel"] or 0)} for f in fuel_data]
                avg_fuel = sum(f["amount"] for f in fuel_summary) / len(fuel_summary) if fuel_summary else 0
                
                from datetime import datetime, timedelta
                today = datetime.now()
                fuel_forecasts = []
                for i in range(1, int(months) + 1):
                    future_month = (today.replace(day=1) + timedelta(days=32*i)).replace(day=1)
                    fuel_forecasts.append({
                        "month": future_month.strftime("%Y-%m"),
                        "optimistic": round(avg_fuel * 0.85, 2),
                        "base": round(avg_fuel, 2),
                        "pessimistic": round(avg_fuel * 1.15, 2),
                        "trend": "stable"
                    })
                forecasts_by_category["fuel"] = fuel_forecasts
        
        # Maintenance expenses
        if category in ["all", "maintenance"]:
            maint_data = db.execute("""
                SELECT job_date, SUM(total_cost) AS total_maint
                FROM maintenance_jobs
                WHERE job_date IS NOT NULL
                GROUP BY job_date
                ORDER BY job_date DESC
                LIMIT 24
            """).fetchall()
            
            if maint_data:
                maint_summary = [{"date": m["job_date"], "amount": float(m["total_maint"] or 0)} for m in maint_data]
                avg_maint = sum(m["amount"] for m in maint_summary) / len(maint_summary) if maint_summary else 0
                
                from datetime import datetime, timedelta
                today = datetime.now()
                maint_forecasts = []
                for i in range(1, int(months) + 1):
                    future_month = (today.replace(day=1) + timedelta(days=32*i)).replace(day=1)
                    maint_forecasts.append({
                        "month": future_month.strftime("%Y-%m"),
                        "optimistic": round(avg_maint * 0.8, 2),
                        "base": round(avg_maint, 2),
                        "pessimistic": round(avg_maint * 1.2, 2),
                        "trend": "stable"
                    })
                forecasts_by_category["maintenance"] = maint_forecasts
        
        # Supplier expenses
        if category in ["all", "suppliers"]:
            supplier_data = db.execute("""
                SELECT invoice_date, SUM(total_amount) AS total_supplier
                FROM supplier_invoices
                WHERE invoice_date IS NOT NULL
                GROUP BY invoice_date
                ORDER BY invoice_date DESC
                LIMIT 24
            """).fetchall()
            
            if supplier_data:
                supplier_summary = [{"date": s["invoice_date"], "amount": float(s["total_supplier"] or 0)} for s in supplier_data]
                avg_supplier = sum(s["amount"] for s in supplier_summary) / len(supplier_summary) if supplier_summary else 0
                
                from datetime import datetime, timedelta
                today = datetime.now()
                supplier_forecasts = []
                for i in range(1, int(months) + 1):
                    future_month = (today.replace(day=1) + timedelta(days=32*i)).replace(day=1)
                    supplier_forecasts.append({
                        "month": future_month.strftime("%Y-%m"),
                        "optimistic": round(avg_supplier * 0.85, 2),
                        "base": round(avg_supplier, 2),
                        "pessimistic": round(avg_supplier * 1.15, 2),
                        "trend": "stable"
                    })
                forecasts_by_category["suppliers"] = supplier_forecasts
        
        return jsonify({
            "forecasts": forecasts_by_category,
            "category": category,
            "method": "calculation"
        })
        
    except Exception as e:
        import traceback
        current_app.logger.error("Expense forecast error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/salary-forecast", methods=["GET"])
def salary_forecast():
    """Salary cost forecast with calculation fallback."""
    try:
        db = open_db()
        months = int(request.args.get("months", "3"))
        
        # Get current employee count and average salary
        current_employees = db.execute("""
            SELECT COUNT(*) AS cnt, AVG(basic_salary) AS avg_salary
            FROM employees
            WHERE status = 'Active'
        """).fetchone()
        
        current_count = current_employees["cnt"] or 0 if current_employees else 0
        avg_salary = float(current_employees["avg_salary"] or 0) if current_employees else 0
        
        # Get historical data
        historical = db.execute("""
            SELECT salary_month, SUM(net_payable) AS total_salary, COUNT(*) AS employee_count
            FROM salary_payments
            WHERE salary_month IS NOT NULL
            GROUP BY salary_month
            ORDER BY salary_month DESC
            LIMIT 24
        """).fetchall()
        
        data_summary = [{
            "month": r["salary_month"],
            "total_salary": float(r["total_salary"] or 0),
            "employee_count": r["employee_count"]
        } for r in historical]
        
        # Fast calculation fallback (always works)
        base_monthly = max(current_count * avg_salary * 1.1, 1)
        from datetime import datetime, timedelta
        today = datetime.now()
        forecasts = []
        for i in range(1, months + 1):
            future_month = (today.replace(day=1) + timedelta(days=32*i)).replace(day=1)
            forecasts.append({
                "month": future_month.strftime("%Y-%m"),
                "optimistic": round(base_monthly * 0.9, 2),
                "base": round(base_monthly, 2),
                "pessimistic": round(base_monthly * 1.1, 2),
                "trend": "stable"
            })
        
        # Try AI enhancement with short timeout
        if current_count > 0 and data_summary:
            try:
                prompt = f"""
                Historical salary data (last 24 months):
                {json.dumps(data_summary, indent=2)}
                
                Current active employees: {current_count}
                Average basic salary: {avg_salary:.2f}
                
                Forecast salary costs for the next {months} months with 3 scenarios:
                1. Optimistic, 2. Base, 3. Pessimistic
                
                Respond with JSON only: {{"forecasts": [{{"month": "YYYY-MM", "optimistic": amount, "base": amount, "pessimistic": amount, "trend": "up/down/stable"}}], "summary": "brief insight", "confidence": "high/medium/low"}}
                """
                result, err = _call_llm([{"role": "system", "content": "You are a financial forecasting AI. Respond with JSON only. Use realistic AED amounts."}, {"role": "user", "content": prompt}])
                if not err and isinstance(result, dict):
                    ai_forecasts = result.get("forecasts", [])
                    if ai_forecasts:
                        return jsonify({
                            "forecasts": ai_forecasts[:months],
                            "summary": result.get("summary", ""),
                            "confidence": result.get("confidence", "medium"),
                            "historical": data_summary[:6],
                            "current_employees": current_count,
                            "method": "ai"
                        })
            except Exception:
                pass
        
        return jsonify({
            "forecasts": forecasts,
            "summary": f"Based on {current_count} active employees, avg salary AED {avg_salary:.2f}",
            "confidence": "medium",
            "historical": data_summary[:6],
            "current_employees": current_count,
            "method": "calculation"
        })
        
    except Exception as e:
        import traceback
        current_app.logger.error("Salary forecast error: %s\n%s", e, traceback.format_exc())
        return jsonify({
            "forecasts": [],
            "summary": "Unable to compute forecast.",
            "confidence": "low",
            "method": "error"
        })


@ai_bp.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        if not data or "message" not in data:
            return jsonify({"error": "Message is required"}), 400

        user_msg = data["message"].strip()
        history = data.get("history", [])
        chat_lang = data.get("lang", "en")
        today = date.today().isoformat()
        schema = _get_schema()

        lang_instruction = (
            "Respond in English."
            if chat_lang == "en"
            else "Urdu mein jawab dein. (Respond in Urdu.)"
        )

        company_desc = (
            "Company: Current Link General Contracting LLC (currentlinkgc.com)\n"
            "Developer: Waqar Hussain (Viki) — created this ERP system.\n"
        )

        system = (
            f"You are Current Link ERP Assistant — a highly professional AI assistant.\n"
            f"Today: {today}\n"
            f"{company_desc}"
            f"{lang_instruction}\n\n"
            f"Database tables and columns:\n{schema}\n\n"
            "Capabilities:\n"
            "1. READ: Answer questions by querying the database with SELECT SQL.\n"
            "2. WRITE: Create, update, or delete records when the user asks. Execute INSERT/UPDATE/DELETE directly.\n"
            "3. CHAT: Answer general questions without SQL (identity, greetings, etc.).\n\n"
            "Identity facts (do NOT query the database for these):\n"
            "- You were created by Waqar Hussain (Viki).\n"
            "- You are the Current Link ERP Assistant for Current Link General Contracting LLC.\n"
            "- The ERP system manages drivers, vehicles, employees, fuel, customers, invoices, suppliers, and more.\n\n"
            "Reply ONLY with JSON. Choose the format based on the user's intent:\n"
            '  - For READ: {"sql":"SELECT ...", "explanation":"answer for the user"}\n'
            '  - For WRITE: {"sql":"INSERT/UPDATE/DELETE ...", "explanation":"what will be done"}\n'
            '  - For CHAT/no SQL: {"explanation":"your reply", "sql":""}\n\n'
            "Rules:\n"
            "- Always use AS aliases for computed or ambiguous columns.\n"
            "- Use PostgreSQL-compatible syntax (ILIKE for case-insensitive, %s style if needed — the adapter handles ? to %s conversion).\n"
            "- For write operations, the SQL will be executed immediately and committed.\n"
            "- Be concise, professional, and data-driven.\n"
            "- When the user asks 'who created you' or similar, say 'Waqar Hussain (Viki)' — do NOT query the database.\n"
            "Examples:\n"
            '  {"sql":"SELECT count(*) AS cnt FROM drivers WHERE status=\'Active\'","explanation":"There are 15 active drivers."}\n'
            '  {"sql":"INSERT INTO fuel_entries (vehicle_plate, entry_date, gallons, rate_per_gallon, total_amount, supplier_name) VALUES (\'ABC123\', \'2026-07-04\', 50, 2.5, 125, \'Adnoc\')","explanation":"Fuel entry created: 50 GLN at 2.5/GLN = AED 125 for ABC123."}\n'
            '  {"explanation":"I was created by Waqar Hussain (Viki), the developer of Current Link ERP.","sql":""}\n'
        )

        messages = [{"role": "system", "content": system}]
        for h in history[-10:]:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_msg})

        result, err = _call_llm(messages)
        if err:
            return jsonify({"error": err}), 500

        if not isinstance(result, dict):
            return jsonify({"reply": str(result), "sql": None, "data": None})

        explanation = result.get("explanation", "")
        sql = result.get("sql", "")

        if not sql:
            return jsonify({"reply": explanation or "Done.", "sql": None, "data": None})

        # Auto-retry SQL on failure (up to 2 times)
        for attempt in range(3):
            rows = _execute_sql(sql)
            if not isinstance(rows, dict) or "error" not in rows:
                break
            if attempt < 2:
                fix_prompt = f"The previous SQL had an error: {rows['error']}. Fix the SQL for PostgreSQL and respond with JSON only. Original question: {user_msg}. Schema: {schema}"
                fix_result, fix_err = _call_llm([{"role": "system", "content": "Fix SQL errors. Reply JSON only."}, {"role": "user", "content": fix_prompt}])
                if fix_result and isinstance(fix_result, dict) and fix_result.get("sql"):
                    sql = fix_result["sql"]
                    explanation = fix_result.get("explanation", explanation)
                else:
                    break
        else:
            return jsonify({"reply": "Mujhe samajh nahi aaya. Kuch aur tarah se poochiye.", "sql": None, "data": None})

        # For write operations, return the success message
        if isinstance(rows, dict) and "affected" in rows:
            return jsonify({
                "reply": explanation or "Done.",
                "sql": sql,
                "data": rows.get("row") or rows.get("affected"),
            })

        if rows and explanation:
            for row in rows[:1]:
                for k, v in row.items():
                    explanation = explanation.replace("{" + k + "}", str(v if v is not None else "0"))

        explanation = re.sub(r'(?m)^SQL:.*$', '', explanation).strip()
        explanation = re.sub(r'\{[^}]+\}', '', explanation).strip()

        return jsonify({"reply": explanation or "Done.", "sql": sql, "data": rows[:20] if rows else None})

    except Exception as e:
        import traceback
        current_app.logger.error("AI Chat error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": f"Server error: {e}"}), 500
