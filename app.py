from flask import Flask, render_template, request, jsonify
import sqlite3, os, json, smtplib, threading
from datetime import datetime, date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import random, string

app = Flask(__name__)
app.secret_key = "medease_secret_key_2024"
DB = "database/medease.db"

# ── EMAIL CONFIG ──────────────────────────────────────────────────────────────
EMAIL_SENDER   = "medeasecaree@gmail.com"
EMAIL_PASSWORD = "dzdz qacd jqub kxnr"   # Gmail App Password

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
            patient_email TEXT,
            doctor_id INTEGER,
            doctor_name TEXT,
            date TEXT,
            time_slot TEXT,
            token TEXT,
            status TEXT DEFAULT 'pending',
            intake_data TEXT DEFAULT '{}',
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
        CREATE TABLE IF NOT EXISTS email_reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appointment_id INTEGER,
            reminder_type TEXT,
            sent INTEGER DEFAULT 0,
            scheduled_at TEXT,
            sent_at TEXT
        );
    """)

    # Migrations — safe to run on existing DB
    for col, definition in [
        ("intake_data",    "TEXT DEFAULT '{}'"),
        ("patient_email",  "TEXT DEFAULT ''"),
    ]:
        try:
            db.execute(f"ALTER TABLE appointments ADD COLUMN {col} {definition}")
            db.commit()
        except Exception:
            pass

    count = db.execute("SELECT COUNT(*) FROM doctors").fetchone()[0]
    if count == 0:
        doctors = [
            ("Dr. Priya Sharma",   "Cardiology",       1, 0, 700),
            ("Dr. Rahul Mehta",    "Orthopedics",      1, 2, 600),
            ("Dr. Sneha Kulkarni", "Dermatology",      1, 1, 500),
            ("Dr. Amit Desai",     "Neurology",        1, 0, 800),
            ("Dr. Pooja Joshi",    "Pediatrics",       1, 3, 450),
            ("Dr. Vijay Nair",     "General Medicine", 1, 4, 300),
        ]
        db.executemany(
            "INSERT INTO doctors (name, specialty, available, queue_count, fee) VALUES (?,?,?,?,?)",
            doctors
        )
    db.commit()
    db.close()

# ── EMAIL HELPERS ─────────────────────────────────────────────────────────────

def build_intake_html(intake_json, specialty):
    """Convert intake_data JSON into a nicely formatted HTML table."""
    try:
        data = json.loads(intake_json) if intake_json else {}
    except Exception:
        data = {}
    if not data:
        return "<p style='color:#64748b'>No intake form data recorded.</p>"

    rows = ""
    for key, value in data.items():
        if not value:
            continue
        label = key.replace("_", " ").title()
        rows += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;font-weight:600;color:#1a2332;width:40%;font-size:13px">{label}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;color:#475569;font-size:13px">{value}</td>
        </tr>"""
    if not rows:
        return "<p style='color:#64748b'>No intake form data recorded.</p>"
    return f"""
    <table style="width:100%;border-collapse:collapse;background:#f8fafc;border-radius:10px;overflow:hidden;border:1px solid #e2e8f0">
      <thead>
        <tr style="background:#0ea5a0">
          <th colspan="2" style="padding:10px 14px;color:white;text-align:left;font-size:13px;letter-spacing:1px">
            🏥 {specialty} Intake Form
          </th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>"""

def build_reminder_email(appt, hours_before):
    """Build the HTML reminder email."""
    if hours_before == 12:
        urgency = "⏰ Appointment Tomorrow"
        color   = "#0ea5a0"
        msg     = "You have an appointment scheduled tomorrow. Please make sure you are prepared!"
    elif hours_before == 5:
        urgency = "🔔 Appointment in 5 Hours"
        color   = "#f97316"
        msg     = "Your appointment is coming up in about 5 hours. Please plan your travel accordingly."
    elif hours_before == 2:
        urgency = "⚡ Appointment in 2 Hours"
        color   = "#dc2626"
        msg     = "Your appointment is just 2 hours away! Please start getting ready."
    else:
        urgency = "🚨 Appointment in 1 Hour"
        color   = "#7c3aed"
        msg     = "Your appointment is just 1 hour away! Please leave now to reach on time."

    intake_html = build_intake_html(
        appt.get("intake_data", "{}"),
        appt.get("doctor_name", "Doctor")
    )

    html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f0f4f8;font-family:'Segoe UI',Arial,sans-serif">
  <div style="max-width:580px;margin:30px auto;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08)">

    <!-- Header -->
    <div style="background:{color};padding:28px 32px">
      <div style="font-size:22px;font-weight:800;color:white;letter-spacing:-0.5px">MedEase 🏥</div>
      <div style="font-size:18px;font-weight:700;color:rgba(255,255,255,0.95);margin-top:6px">{urgency}</div>
    </div>

    <!-- Body -->
    <div style="padding:28px 32px">
      <p style="font-size:15px;color:#1a2332;margin-bottom:6px">Dear <strong>{appt['patient_name']}</strong>,</p>
      <p style="font-size:14px;color:#475569;line-height:1.6;margin-bottom:24px">{msg}</p>

      <!-- Appointment Card -->
      <div style="background:#e6f7f6;border:1px solid rgba(14,165,160,0.25);border-radius:12px;padding:20px;margin-bottom:24px">
        <div style="font-size:13px;font-weight:700;color:#0ea5a0;letter-spacing:1px;text-transform:uppercase;margin-bottom:14px">📋 Appointment Details</div>
        <table style="width:100%;border-collapse:collapse">
          <tr>
            <td style="padding:5px 0;font-size:13px;color:#64748b;width:40%">👨‍⚕️ Doctor</td>
            <td style="padding:5px 0;font-size:13px;font-weight:600;color:#1a2332">{appt['doctor_name']}</td>
          </tr>
          <tr>
            <td style="padding:5px 0;font-size:13px;color:#64748b">📅 Date</td>
            <td style="padding:5px 0;font-size:13px;font-weight:600;color:#1a2332">{appt['date']}</td>
          </tr>
          <tr>
            <td style="padding:5px 0;font-size:13px;color:#64748b">🕐 Time</td>
            <td style="padding:5px 0;font-size:13px;font-weight:600;color:#1a2332">{appt['time_slot']}</td>
          </tr>
          <tr>
            <td style="padding:5px 0;font-size:13px;color:#64748b">🎫 Token</td>
            <td style="padding:5px 0;font-size:13px;font-weight:800;color:#0ea5a0;font-size:16px">{appt['token']}</td>
          </tr>
        </table>
      </div>

      <!-- Intake Form -->
      <div style="margin-bottom:24px">
        <div style="font-size:13px;font-weight:700;color:#1a2332;letter-spacing:1px;text-transform:uppercase;margin-bottom:12px">📝 Your Medical Intake Form</div>
        {intake_html}
      </div>

      <!-- Tips -->
      <div style="background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:16px;margin-bottom:24px">
        <div style="font-size:13px;font-weight:700;color:#92400e;margin-bottom:8px">💡 Please Remember</div>
        <ul style="margin:0;padding-left:18px;font-size:13px;color:#78350f;line-height:1.8">
          <li>Bring your token number <strong>{appt['token']}</strong> to reception</li>
          <li>Carry any previous medical reports or prescriptions</li>
          <li>Arrive 10 minutes early</li>
          <li>Wear a mask inside the hospital premises</li>
        </ul>
      </div>

      <p style="font-size:13px;color:#64748b">Need help? Call us at <strong>+91 94045 01044</strong> or email <a href="mailto:medeasecaree@gmail.com" style="color:#0ea5a0">medeasecaree@gmail.com</a></p>
    </div>

    <!-- Footer -->
    <div style="background:#1a2332;padding:18px 32px;text-align:center">
      <p style="color:#94a3b8;font-size:12px;margin:0">© MedEase OPD Management System · This is an automated reminder</p>
    </div>
  </div>
</body>
</html>"""
    return html

def send_email(to_email, subject, html_body):
    """Send email via Gmail SMTP."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"MedEase Hospital <{EMAIL_SENDER}>"
        msg["To"]      = to_email
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, to_email, msg.as_string())
        print(f"[EMAIL] ✅ Sent to {to_email} — {subject}")
        return True
    except Exception as e:
        print(f"[EMAIL] ❌ Failed to {to_email}: {e}")
        return False

def schedule_reminders(appointment_id):
    """Schedule 4 reminder emails for an appointment (runs in background thread)."""
    def _run():
        db = get_db()
        appt = db.execute("SELECT * FROM appointments WHERE id=?", (appointment_id,)).fetchone()
        if not appt:
            db.close()
            return
        appt = dict(appt)
        patient_email = appt.get("patient_email", "").strip()
        if not patient_email:
            print(f"[EMAIL] No email for appointment {appointment_id}, skipping reminders.")
            db.close()
            return

        # Parse appointment datetime
        try:
            appt_dt = datetime.strptime(f"{appt['date']} {appt['time_slot']}", "%Y-%m-%d %I:%M %p")
        except Exception:
            try:
                appt_dt = datetime.strptime(f"{appt['date']} {appt['time_slot']}", "%Y-%m-%d %H:%M")
            except Exception as e:
                print(f"[EMAIL] Could not parse datetime: {e}")
                db.close()
                return

        reminders = [
            (12, "⏰ Appointment Reminder — 12 Hours to Go | MedEase"),
            (5,  "🔔 Appointment Reminder — 5 Hours to Go | MedEase"),
            (2,  "⚡ Appointment Reminder — 2 Hours to Go | MedEase"),
            (1,  "🚨 Appointment Reminder — 1 Hour to Go | MedEase"),
        ]

        now = datetime.now()
        for hours_before, subject in reminders:
            send_at = appt_dt - timedelta(hours=hours_before)
            if send_at <= now:
                print(f"[EMAIL] Skipping {hours_before}hr reminder (time already passed)")
                continue
            wait_seconds = (send_at - now).total_seconds()
            # Register in DB
            db.execute(
                "INSERT INTO email_reminders (appointment_id, reminder_type, scheduled_at) VALUES (?,?,?)",
                (appointment_id, f"{hours_before}hr", send_at.strftime("%Y-%m-%d %H:%M:%S"))
            )
            db.commit()
            # Schedule in a timer thread
            def _send(h=hours_before, s=subject, r_at=send_at, w=wait_seconds):
                print(f"[EMAIL] Waiting {w:.0f}s to send {h}hr reminder...")
                import time; time.sleep(w)
                html = build_reminder_email(appt, h)
                ok = send_email(patient_email, s, html)
                # Update sent status
                try:
                    conn = get_db()
                    conn.execute(
                        "UPDATE email_reminders SET sent=?, sent_at=? WHERE appointment_id=? AND reminder_type=?",
                        (1 if ok else 0, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                         appointment_id, f"{h}hr")
                    )
                    conn.commit(); conn.close()
                except Exception:
                    pass
            t = threading.Timer(wait_seconds, _send)
            t.daemon = True
            t.start()

        db.close()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

# ── PAGE ROUTES ───────────────────────────────────────────────────────────────

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

@app.route("/about")
def about():
    return render_template("about.html")

# ── DOCTORS ───────────────────────────────────────────────────────────────────

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

# ── APPOINTMENTS ──────────────────────────────────────────────────────────────

@app.route("/api/appointments", methods=["GET"])
def get_appointments():
    db = get_db()
    appts = db.execute("SELECT * FROM appointments ORDER BY created_at DESC").fetchall()
    db.close()
    return jsonify([dict(a) for a in appts])

@app.route("/api/appointments", methods=["POST"])
def book_appointment():
    data = request.json
    db = get_db()

    existing = db.execute(
        "SELECT id FROM appointments WHERE doctor_id=? AND date=? AND time_slot=?",
        (data["doctor_id"], data["date"], data["time_slot"])
    ).fetchone()
    if existing:
        db.close()
        return jsonify({"success": False, "message": "This time slot is already booked. Please choose a different time."})

    token        = "TKN" + "".join(random.choices(string.digits, k=4))
    intake_json  = data.get("intake_data", "{}")
    patient_email= data.get("patient_email", "").strip()

    db.execute(
        """INSERT INTO appointments
           (patient_name, patient_phone, patient_email, doctor_id, doctor_name,
            date, time_slot, token, intake_data)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (data["patient_name"], data["patient_phone"], patient_email,
         data["doctor_id"], data["doctor_name"],
         data["date"], data["time_slot"], token, intake_json)
    )
    appt_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    pos = db.execute(
        "SELECT COUNT(*) FROM queue WHERE doctor_id=? AND status='waiting'",
        (data["doctor_id"],)
    ).fetchone()[0] + 1
    db.execute(
        "INSERT INTO queue (doctor_id, patient_name, token, position) VALUES (?,?,?,?)",
        (data["doctor_id"], data["patient_name"], token, pos)
    )
    db.execute("UPDATE doctors SET queue_count=queue_count+1 WHERE id=?", (data["doctor_id"],))
    db.commit()
    db.close()

    # Schedule email reminders in background (only if email provided)
    if patient_email:
        schedule_reminders(appt_id)

    return jsonify({"success": True, "token": token})

@app.route("/api/appointments/<int:appt_id>/status", methods=["POST"])
def update_appointment_status(appt_id):
    data = request.get_json()
    db = get_db()
    db.execute("UPDATE appointments SET status=? WHERE id=?", (data.get("status","pending"), appt_id))
    db.commit()
    db.close()
    return jsonify({"success": True})

@app.route("/api/appointments/<int:appt_id>/edit", methods=["POST"])
def edit_appointment(appt_id):
    data = request.get_json()
    db = get_db()
    db.execute(
        "UPDATE appointments SET patient_name=?, patient_phone=?, doctor_name=?, date=?, time_slot=?, status=? WHERE id=?",
        (data.get("patient_name"), data.get("patient_phone"), data.get("doctor_name"),
         data.get("date"), data.get("time_slot"), data.get("status"), appt_id)
    )
    db.commit()
    db.close()
    return jsonify({"success": True})

@app.route("/api/appointments/<int:appt_id>/delete", methods=["POST"])
def delete_appointment(appt_id):
    db = get_db()
    db.execute("DELETE FROM appointments WHERE id=?", (appt_id,))
    db.commit()
    db.close()
    return jsonify({"success": True})

# ── QUEUE ─────────────────────────────────────────────────────────────────────

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

# ── PAYMENTS ──────────────────────────────────────────────────────────────────

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

@app.route("/api/payments/<int:pay_id>/edit", methods=["POST"])
def edit_payment(pay_id):
    data = request.get_json()
    db = get_db()
    db.execute(
        "UPDATE payments SET patient_name=?, amount=?, status=?, transaction_id=? WHERE id=?",
        (data.get("patient_name"), data.get("amount"), data.get("status"),
         data.get("transaction_id"), pay_id)
    )
    db.commit()
    db.close()
    return jsonify({"success": True})

@app.route("/api/payments/<int:pay_id>/delete", methods=["POST"])
def delete_payment(pay_id):
    db = get_db()
    db.execute("DELETE FROM payments WHERE id=?", (pay_id,))
    db.commit()
    db.close()
    return jsonify({"success": True})

# ── STATS ─────────────────────────────────────────────────────────────────────

@app.route("/api/stats")
def get_stats():
    db = get_db()
    total_appts    = db.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
    today_appts    = db.execute("SELECT COUNT(*) FROM appointments WHERE date=?", (str(date.today()),)).fetchone()[0]
    total_revenue  = db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='confirmed'").fetchone()[0]
    active_doctors = db.execute("SELECT COUNT(*) FROM doctors WHERE available=1").fetchone()[0]
    in_queue       = db.execute("SELECT COUNT(*) FROM queue WHERE status='waiting'").fetchone()[0]
    recent_appts   = db.execute("SELECT * FROM appointments ORDER BY created_at DESC LIMIT 8").fetchall()
    recent_payments= db.execute("SELECT * FROM payments ORDER BY created_at DESC LIMIT 6").fetchall()
    db.close()
    return jsonify({
        "total_appointments":  total_appts,
        "today_appointments":  today_appts,
        "total_revenue":       total_revenue,
        "active_doctors":      active_doctors,
        "in_queue":            in_queue,
        "recent_appointments": [dict(a) for a in recent_appts],
        "recent_payments":     [dict(p) for p in recent_payments],
    })

# ── CHATBOT ───────────────────────────────────────────────────────────────────

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
        return jsonify({"reply": f"Currently {in_queue} patient(s) are waiting in queue. Estimated wait: ~{in_queue * 10} minutes.\n\nCheck live queue status on the Queue page."})
    elif any(w in msg for w in ["hello", "hi", "hey", "help"]):
        db.close()
        return jsonify({"reply": "Hello! I'm MedBot 🏥 — your MedEase virtual assistant.\n\nI can help you with:\n• Finding available doctors\n• Booking appointments\n• Payment information\n• Queue status\n• General hospital queries\n\nWhat do you need help with?"})
    elif any(w in msg for w in ["timing", "hour", "open", "time"]):
        db.close()
        return jsonify({"reply": "MedEase OPD Hours:\n🕗 Morning: 8:00 AM – 1:00 PM\n🕔 Evening: 4:00 PM – 8:00 PM\n\nEmergency services available 24/7."})
    else:
        db.close()
        return jsonify({"reply": "I'm not sure about that. I can help with:\n• Doctor availability\n• Appointment booking\n• Payment info\n• Queue status\n• Hospital timings"})

if __name__ == "__main__":
    os.makedirs("database", exist_ok=True)
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
