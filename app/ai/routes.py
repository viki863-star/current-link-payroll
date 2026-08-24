import json
import re
import os
from datetime import date
from flask import request, jsonify, current_app, session
from . import ai_bp
from ..database import open_db
from app import csrf

from google import genai

TABLES = [
    "drivers", "employees", "vehicles", "salary_store", "salary_slips",
    "supplier_invoices", "customer_invoices", "account_invoices",
    "fuel_entries", "maintenance_jobs", "maintenance_papers",
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
                    "SELECT column_name FROM information_schema.columns WHERE table_name = ? ORDER BY ordinal_position",
                    (table,),
                ).fetchall()
                if cols:
                    names = [c['column_name'] for c in cols]
                    lines.append(f"{table}({', '.join(names)})")
            else:
                cols = db.execute(f"PRAGMA table_info({table})").fetchall()
                if cols:
                    names = [c['name'] for c in cols]
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


_gemini_client = None

def _get_client():
    global _gemini_client
    if _gemini_client is None:
        api_key = os.getenv("AI_API_KEY") or ""
        if api_key:
            _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client


def _call_llm(messages, max_tokens=1024):
    api_key = os.getenv("AI_API_KEY") or ""
    api_model = os.getenv("AI_MODEL", "gemini-3.5-flash-lite")

    if not api_key:
        return None, "AI assistant is not configured yet. Please set AI_API_KEY in .env"

    try:
        client = _get_client()
        if client is None:
            return None, "Failed to initialize AI client"

        system_msg = ""
        user_msgs = []
        for m in messages:
            if m["role"] == "system":
                system_msg += m["content"] + "\n\n"
            else:
                user_msgs.append(m["content"])

        full_prompt = system_msg + "\n\n".join(user_msgs)

        response = client.models.generate_content(
            model=api_model,
            contents=full_prompt,
            config=genai.types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=max_tokens,
            )
        )

        raw = response.text.strip()
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

        return {"explanation": raw, "sql": ""}, None
    except Exception as e:
        return None, str(e)


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


_cached_schema = None
_schema_fetched = False

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

        global _cached_schema, _schema_fetched
        if not _schema_fetched:
            _cached_schema = _get_schema()
            _schema_fetched = True
        schema = _cached_schema

        lang_instruction = "Respond in English." if chat_lang == "en" else "Urdu mein jawab dein."

        system = (
            f"You are VIKI - a powerful, friendly, and intelligent AI assistant created by Waqar Hussain for Current Link ERP (UAE transport company). Date: {today}. {lang_instruction}\n\n"
            f"You are like ChatGPT - you can answer ANYTHING:\n"
            "- General chat, greetings, jokes, stories, advice\n"
            "- Math, calculations, conversions\n"
            "- Business strategy, HR advice, fleet management tips\n"
            "- Writing emails, reports, letters\n"
            "- Translation (Arabic, English, Urdu)\n"
            "- Science, history, geography, general knowledge\n"
            "- Code help, technical questions\n"
            "- Life advice, motivational quotes\n\n"
            f"DATABASE SCHEMA (use ONLY when user asks about THEIR data):\n{schema}\n\n"
            "RESPONSE FORMATS:\n\n"
            "A) For GENERAL CHAT (hi, hello, how are you, jokes, advice, knowledge, anything non-data):\n"
            '{"explanation":"your natural, friendly, helpful response", "sql":""}\n\n'
            "B) For ERP DATA QUESTIONS (asking about drivers, salary, invoices, customers, etc.):\n"
            '{"sql":"SELECT ...", "explanation":"natural answer with the data woven in"}\n\n'
            "C) For WRITE OPERATIONS (only when user explicitly asks to add/update/delete):\n"
            '{"sql":"INSERT/UPDATE/DELETE ...", "explanation":"what was done"}\n\n'
            "PERSONALITY:\n"
            "- Be warm, friendly, and conversational like a helpful colleague\n"
            "- Use emojis occasionally (not too many)\n"
            "- Tell jokes if asked\n"
            "- Be witty and fun but professional\n"
            "- If you dont know something, say so honestly\n"
            "- For data answers: weave the number into a natural sentence, don't just say the number\n"
            "  Good: 'You have 54 active drivers in the fleet! 🚛'\n"
            "  Bad: 'count: 54'\n"
            "  Good: 'The total salary for August is AED 3,480 💰'\n"
            "  Bad: 'sum: 3480.0'"
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

        if rows and isinstance(rows, list) and len(rows) > 0:
            first_row = rows[0]
            data_str = ", ".join(f"{k}: {v}" for k, v in first_row.items() if v is not None)
            if data_str and data_str not in explanation:
                explanation = f"{explanation}\n\n📊 **{data_str}**"

        return jsonify({"reply": explanation or "Done.", "sql": sql, "data": rows[:20] if rows else None})

    except Exception as e:
        import traceback
        current_app.logger.error("AI Chat error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": f"Server error: {e}"}), 500
