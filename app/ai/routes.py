import json
import re
import os
import requests
from datetime import date
from flask import request, jsonify, current_app
from . import ai_bp
from ..database import open_db

TABLES = [
    "employees", "drivers", "field_staff", "cash_receipts", "vehicles",
    "vehicle_assignments", "salary_store", "salary_slips", "salary_payments",
    "maintenance_jobs", "technicians", "maintenance_staff_advances",
    "maintenance_papers", "parties", "suppliers", "supplier_invoices",
    "supplier_bills", "account_invoices", "account_invoice_lines",
    "account_payments", "fuel_entries",
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


def _execute_sql(sql):
    db = open_db()
    try:
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
        "max_tokens": 1024,
    }

    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=30)
        data = resp.json()
        if "choices" not in data or not data["choices"]:
            err = data.get("error", {}).get("message", str(data))
            return None, f"AI error: {err}"

        raw = data["choices"][0]["message"]["content"].strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        raw = raw.strip()

        json_match = re.search(r'\{[^{}]*"sql"[^{}]*\}', raw, re.DOTALL)
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


@ai_bp.route("/tripsheet_save", methods=["POST"])
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
        db.execute("""INSERT INTO tabreed_tripsheets
            (customer_id, entry_date, time_in, time_out, total_reading, tanker_gln, trips, tanker_reg, notes)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (cid, entry_date, time_in or None, time_out or None, total_reading, tanker_gln or None, trips, tanker_reg or None, notes or None))
        db.commit()
        db.close()
        return jsonify({"success": True, "message": "Tripsheet entry saved"})
    except Exception as e:
        import traceback
        current_app.logger.error("Tripsheet save error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500


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
            "Respond in English." if chat_lang == "en"
            else "Urdu mein jawab dein. (Respond in Urdu.)"
        )
        system = (
            f"Date:{today}. ERP SQL assistant.\n"
            f"Database schema (exact column names):\n{schema}\n"
            f"{lang_instruction}\n"
            "Reply ONLY JSON: {\"sql\":\"SELECT...\",\"explanation\":\"answer\"}. "
            "SELECT only. ALWAYS use AS aliases. "
            'Ex: {"sql":"SELECT count(*) AS cnt FROM drivers WHERE status=\'Active\'","explanation":"15 active drivers"}'
        )

        messages = [{"role": "system", "content": system}]
        for h in history[-8:]:
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
