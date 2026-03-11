from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import sqlite3, os, json
from datetime import datetime, date
import random, string

app = Flask(__name__)
app.secret_key = "medease_secret_key_2024"
DB = "database/medease.db"

# ─── Database Init ────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            age INTEGER,
            gender TEXT,
            phone TEXT,
            email TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            specialty TEXT,
            available INTEGER DEFAULT 1,
            queue_count INTEGER DEFAULT 0,
            fee INTEGER DEFAULT 500
        );
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_name TEXT,
            patient_phone TEXT,
            doctor_id INTEGER,
            doctor_name TEXT,
            date TEXT,
            time_slot TEXT,
            token TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appointment_id INTEGER,
            patient_name TEXT,
            amount REAL,
            transaction_id TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER,
            patient_name TEXT,
            token TEXT,
            position INTEGER,
            status TEXT DEFAULT 'waiting',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Seed doctors if empty
    count = db.execute("SELECT COUNT(*) FROM doctors").fetchone()[0]
    if count == 0:
        doctors = [
            ("Dr. Priya Sharma",   "Cardiology",      1, 0, 700),
            ("Dr. Rahul Mehta",    "Orthopedics",     1, 2, 600),
            ("Dr. Sneha Kulkarni", "Dermatology",     1, 1, 500),
            ("Dr. Amit Desai",     "Neurology",       0, 0, 800),
            ("Dr. Pooja Joshi",    "Pediatrics",      1, 3, 450),
            ("Dr. Vijay Nair",     "General Medicine",1, 4, 300),
        ]
        db.executemany(
            "INSERT INTO doctors (name, specialty, available, queue_count, fee) VALUES (?,?,?,?,?)",
            doctors
        )
    db.commit()
    db.close()

# ─── Pages ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/appointment")
def appointment():
    return render_template("appointment.html")

@app.route("/queue")
def queue_page():
    return render_template("queue.html")

@app.route("/payment")
def payment():
    return render_template("payment.html")

@app.route("/admin")
def admin():
    return render_template("admin.html")

@app.route("/chatbot")
def chatbot():
    return render_template("chatbot.html")

# ─── API: Doctors ─────────────────────────────────────────────────────────────
@app.route("/api/doctors")
def get_doctors():
    db = get_db()
    doctors = db.execute("SELECT * FROM doctors").fetchall()
    db.close()
    return jsonify([dict(d) for d in doctors])

@app.route("/api/doctors/<int:doc_id>/toggle", methods=["POST"])
def toggle_doctor(doc_id):
    db = get_db()
    doc = db.execute("SELECT available FROM doctors WHERE id=?", (doc_id,)).fetchone()
    new_val = 0 if doc["available"] else 1
    db.execute("UPDATE doctors SET available=? WHERE id=?", (new_val, doc_id))
    db.commit()
    db.close()
    return jsonify({"success": True, "available": new_val})

# ─── API: Appointments ────────────────────────────────────────────────────────
@app.route("/api/appointments", methods=["GET"])
def get_appointments():
    db = get_db()
    appts = db.execute("SELECT * FROM appointments ORDER BY created_at DESC").fetchall()
    db.close()
    return jsonify([dict(a) for a in appts])

@app.route("/api/appointments", methods=["POST"])
def book_appointment():
    data = request.json
    token = "TKN" + "".join(random.choices(string.digits, k=4))
    db = get_db()
    db.execute(
        "INSERT INTO appointments (patient_name, patient_phone, doctor_id, doctor_name, date, time_slot, token) VALUES (?,?,?,?,?,?,?)",
        (data["patient_name"], data["patient_phone"], data["doctor_id"],
         data["doctor_name"], data["date"], data["time_slot"], token)
    )
    # Add to queue
    pos = db.execute("SELECT COUNT(*) FROM queue WHERE doctor_id=? AND status='waiting'", (data["doctor_id"],)).fetchone()[0] + 1
    db.execute(
        "INSERT INTO queue (doctor_id, patient_name, token, position) VALUES (?,?,?,?)",
        (data["doctor_id"], data["patient_name"], token, pos)
    )
    db.execute("UPDATE doctors SET queue_count=queue_count+1 WHERE id=?", (data["doctor_id"],))
    db.commit()
    db.close()
    return jsonify({"success": True, "token": token})

# ─── API: Queue ───────────────────────────────────────────────────────────────
@app.route("/api/queue")
def get_queue():
    db = get_db()
    queue = db.execute("""
        SELECT q.*, d.name as doctor_name, d.specialty
        FROM queue q JOIN doctors d ON q.doctor_id = d.id
        WHERE q.status='waiting'
        ORDER BY q.doctor_id, q.position
    """).fetchall()
    db.close()
    return jsonify([dict(q) for q in queue])

@app.route("/api/queue/<int:qid>/next", methods=["POST"])
def next_patient(qid):
    db = get_db()
    db.execute("UPDATE queue SET status='done' WHERE id=?", (qid,))
    q = db.execute("SELECT doctor_id FROM queue WHERE id=?", (qid,)).fetchone()
    if q:
        db.execute("UPDATE doctors SET queue_count=MAX(0,queue_count-1) WHERE id=?", (q["doctor_id"],))
    db.commit()
    db.close()
    return jsonify({"success": True})

# ─── API: Payments ────────────────────────────────────────────────────────────
@app.route("/api/payments", methods=["GET"])
def get_payments():
    db = get_db()
    payments = db.execute("SELECT * FROM payments ORDER BY created_at DESC").fetchall()
    db.close()
    return jsonify([dict(p) for p in payments])

@app.route("/api/payments", methods=["POST"])
def submit_payment():
    data = request.json
    db = get_db()
    db.execute(
        "INSERT INTO payments (patient_name, amount, transaction_id, status) VALUES (?,?,?,?)",
        (data["patient_name"], data["amount"], data["transaction_id"], "confirmed")
    )
    db.commit()
    db.close()
    return jsonify({"success": True})

# ─── API: Stats (Admin) ───────────────────────────────────────────────────────
@app.route("/api/stats")
def get_stats():
    db = get_db()
    total_appts = db.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
    today_appts = db.execute("SELECT COUNT(*) FROM appointments WHERE date=?", (str(date.today()),)).fetchone()[0]
    total_revenue = db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='confirmed'").fetchone()[0]
    active_doctors = db.execute("SELECT COUNT(*) FROM doctors WHERE available=1").fetchone()[0]
    in_queue = db.execute("SELECT COUNT(*) FROM queue WHERE status='waiting'").fetchone()[0]
    recent_appts = db.execute("SELECT * FROM appointments ORDER BY created_at DESC LIMIT 8").fetchall()
    recent_payments = db.execute("SELECT * FROM payments ORDER BY created_at DESC LIMIT 6").fetchall()
    db.close()
    return jsonify({
        "total_appointments": total_appts,
        "today_appointments": today_appts,
        "total_revenue": total_revenue,
        "active_doctors": active_doctors,
        "in_queue": in_queue,
        "recent_appointments": [dict(a) for a in recent_appts],
        "recent_payments": [dict(p) for p in recent_payments],
    })

# ─── API: Chatbot ─────────────────────────────────────────────────────────────
@app.route("/api/chat", methods=["POST"])
def chat():
    msg = request.json.get("message", "").lower()
    db = get_db()

    if any(w in msg for w in ["doctor", "specialist", "available"]):
        docs = db.execute("SELECT name, specialty, available, fee FROM doctors WHERE available=1").fetchall()
        db.close()
        lines = "\n".join([f"• {d['name']} ({d['specialty']}) — ₹{d['fee']}" for d in docs])
        return jsonify({"reply": f"Currently available doctors:\n{lines}\n\nWould you like to book an appointment?"})

    elif any(w in msg for w in ["book", "appointment", "schedule"]):
        db.close()
        return jsonify({"reply": "To book an appointment:\n1. Go to the Appointment page\n2. Enter your details\n3. Choose a doctor & time slot\n4. You'll receive a token number\n\nShall I take you there? Click 'Book Appointment' in the menu."})

    elif any(w in msg for w in ["pay", "payment", "fee", "cost", "upi"]):
        db.close()
        return jsonify({"reply": "MedEase supports UPI payments. OPD fees vary by department:\n• General Medicine: ₹300\n• Pediatrics: ₹450\n• Dermatology: ₹500\n• Orthopedics: ₹600\n• Cardiology: ₹700\n• Neurology: ₹800\n\nYou can pay via UPI QR on the Payment page."})

    elif any(w in msg for w in ["queue", "wait", "token", "how long"]):
        in_queue = db.execute("SELECT COUNT(*) FROM queue WHERE status='waiting'").fetchone()[0]
        db.close()
        return jsonify({"reply": f"Currently {in_queue} patient(s) are waiting in queue. Average wait time is approximately {in_queue * 10} minutes.\n\nYou can check live queue status on the Queue page."})

    elif any(w in msg for w in ["hello", "hi", "hey", "help"]):
        db.close()
        return jsonify({"reply": "Hello! I'm MedBot 🏥 — your MedEase virtual assistant.\n\nI can help you with:\n• Finding available doctors\n• Booking appointments\n• Payment information\n• Queue status\n• General hospital queries\n\nWhat do you need help with?"})

    elif any(w in msg for w in ["timing", "hour", "open", "time"]):
        db.close()
        return jsonify({"reply": "MedEase OPD Hours:\n🕗 Morning: 8:00 AM – 1:00 PM\n🕔 Evening: 4:00 PM – 8:00 PM\n\nEmergency services are available 24/7.\n\nOnline appointments can be booked anytime!"})

    else:
        db.close()
        return jsonify({"reply": "I'm not sure about that. I can help with:\n• Doctor availability\n• Appointment booking\n• Payment info\n• Queue status\n• Hospital timings\n\nPlease try asking about one of these topics!"})

if __name__ == "__main__":
    os.makedirs("database", exist_ok=True)
    init_db()
    import os
port = int(os.environ.get("PORT", 5000))
app.run(debug=False, host="0.0.0.0", port=port)

