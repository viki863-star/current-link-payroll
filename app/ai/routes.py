import json
import re
import os
import requests
from datetime import date
from flask import request, jsonify, current_app
from . import ai_bp
from ..database import open_db

SCHEMA_DESC = """employees(id,full_name,phone,email,type,dept,designation,salary,status,join_date)
drivers(id,full_name,phone,vehicle_no,shift,salary,status)
field_staff(id,full_name,phone,username)
cash_receipts(staff_id,amount,receipt_date)
vehicles(plate_no,type,model,year,status)
vehicle_assignments(vehicle_id,driver_id,assigned_from,is_current)
salary_store(emp_id,month,basic_salary,ot,advances,deductions,net)
salary_slips(emp_id,month,basic_salary,net,status)
salary_payments(emp_id,month,amount,date)
maintenance_jobs(vehicle_id,staff_id,amount,category,status)
technicians(code,user_id,phone)
maintenance_advances(staff_code,amount,date)
maintenance_papers(code,total_amount,status)
parties(code,name,phone,role,status)
suppliers(code,name,category,status)
supplier_invoices(code,inv_no,amount,status)
supplier_bills(code,bill_no,amount,vat,total,status)
account_invoices(inv_no,party_code,total,status)
account_payments(inv_id,amount,date)
fuel_entries(vehicle_id,liters,cost,date)
"""


def _execute_sql(sql):
    db = open_db()
    try:
        result = db.execute(sql).fetchall()
        if not result:
            return []
        return [dict(row) for row in result]
    except Exception as e:
        return {"error": str(e)}


def _call_gemini(messages, api_key=None):
    api_key = api_key or os.getenv("GEMINI_API_KEY") or current_app.config.get("GEMINI_API_KEY", "")
    if not api_key:
        return None, "GEMINI_API_KEY not configured. Set it in .env file."

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"

    gemini_contents = []
    for msg in messages:
        role = "user" if msg["role"] in ("user", "system") else "model"
        gemini_contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    payload = {
        "contents": gemini_contents,
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024},
    }

    try:
        resp = requests.post(url, json=payload, timeout=30)
        data = resp.json()
        if "candidates" not in data or not data["candidates"]:
            err = data.get("error", {}).get("message", str(data))
            return None, f"Gemini API error: {err}"

        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        text = text.strip()

        parsed = json.loads(text)
        return parsed, None
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON from Gemini: {e}\nRaw: {text[:200]}"
    except Exception as e:
        return None, str(e)


@ai_bp.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        if not data or "message" not in data:
            return jsonify({"error": "Message is required"}), 400

        user_msg = data["message"].strip()
        history = data.get("history", [])

        today = date.today().isoformat()
        system = (
            f"Date: {today}. "
            "ERP assistant. Write SQL SELECT. "
            "Schema:\n" + SCHEMA_DESC +
            "Rules: Reply JSON {\"sql\":...,\"explanation\":...}. "
            "SELECT only. Max 20 rows. COALESCE nulls. "
            "Explanation in user's language. "
            "Ex: {\"sql\":\"SELECT count(*) FROM drivers WHERE status='Active'\",\"explanation\":\"15 drivers\"}"
        )

        messages = [{"role": "system", "content": system}]
        for h in history[-8:]:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_msg})

        result, err = _call_gemini(messages)
        if err:
            return jsonify({"error": err}), 500

        if not isinstance(result, dict):
            return jsonify({"reply": str(result), "sql": None, "data": None})

        explanation = result.get("explanation", "")
        sql = result.get("sql", "")

        if not sql:
            return jsonify({"reply": explanation or "Sorry, I couldn't process that.", "sql": None, "data": None})

        rows = _execute_sql(sql)
        if isinstance(rows, dict) and "error" in rows:
            return jsonify({"reply": f"SQL error: {rows['error']}", "sql": sql, "data": None})

        if rows and explanation:
            try:
                for row in rows[:1]:
                    for k, v in row.items():
                        ph = "{" + k + "}"
                        if ph in explanation:
                            explanation = explanation.replace(ph, str(v) if v is not None else "0")
            except Exception:
                pass

        if not explanation and rows:
            parts = []
            for row in rows[:5]:
                parts.append(" | ".join(f"{k}: {v}" for k, v in row.items()))
            explanation = "\n".join(parts)

        return jsonify({"reply": explanation or "Done.", "sql": sql, "data": rows[:20] if rows else None})

    except Exception as e:
        import traceback
        current_app.logger.error("AI Chat error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": f"Server error: {e}"}), 500
