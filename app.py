from flask import Flask, request, jsonify, render_template
from supabase import create_client
from dotenv import load_dotenv
import os
from datetime import datetime

# ---------------- CONFIG ----------------
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Supabase credentials missing")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

app = Flask(__name__)

# ---------------- HOME ----------------
@app.route("/")
def home():
    return render_template("index.html")

# ---------------- STAFF API ----------------
@app.route("/staff", methods=["POST"])
def add_or_update_staff():
    data = request.get_json(force=True)

    staff_id = data.get("staff_id")
    staff_name = data.get("staff_name")
    department = data.get("department")
    busy_9_10 = bool(data.get("busy_9_10"))

    if not staff_id or not staff_name or not department:
        return jsonify({"error": "staff_id, staff_name, department required"}), 400

    existing = supabase.table("staffs") \
        .select("staff_id") \
        .eq("staff_id", staff_id) \
        .execute()

    if existing.data:
        supabase.table("staffs").update({
            "staff_name": staff_name,
            "department": department,
            "busy_9_10": busy_9_10,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("staff_id", staff_id).execute()

        return jsonify({"message": "Staff updated"}), 200

    supabase.table("staffs").insert({
        "staff_id": staff_id,
        "staff_name": staff_name,
        "department": department,
        "busy_9_10": busy_9_10,
        "priority_count": 0
    }).execute()

    return jsonify({"message": "Staff added"}), 201


# ---------------- SCHEDULER (PROGRESSIVE PRIORITY MODEL) ----------------
@app.route("/schedule", methods=["POST"])
def generate_monthly_schedule():
    data = request.get_json(force=True)
    month_input = data.get("month")

    if not month_input:
        return jsonify({"error": "month required"}), 400

    month_date = month_input + "-01"

    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    gates = ["Gate A", "Gate B", "Gate C"]

    scheduled_days = {}
    shortage_days = []

    # total required assignments
    TOTAL_SLOTS = 6 * len(weekdays)

    # fetch staff once
    staff_resp = supabase.table("staffs") \
        .select("*") \
        .eq("busy_9_10", False) \
        .order("priority_count") \
        .execute()

    staff_map = {s["staff_id"]: s for s in staff_resp.data}

    assignments = []

    # progressive consumption loop
    while len(assignments) < TOTAL_SLOTS:
        eligible = sorted(
            staff_map.values(),
            key=lambda s: s["priority_count"]
        )

        if not eligible or eligible[0]["priority_count"] >= 3:
            break  # 🚨 all exhausted

        staff = eligible[0]

        assignments.append(staff["staff_id"])

        # 🔥 IMMEDIATE PRIORITY INCREMENT
        staff["priority_count"] += 1

    # map assignments to weekdays & gates
    idx = 0
    for day in weekdays:
        day_list = []

        for g in gates:
            for _ in range(2):
                if idx >= len(assignments):
                    shortage_days.append(day)
                    break

                staff_id = assignments[idx]
                staff = staff_map[staff_id]

                supabase.table("monthly_schedule").insert({
                    "staff_id": staff_id,
                    "month": month_date,
                    "weekday": day,
                    "gate": g
                }).execute()

                day_list.append({
                    "staff_id": staff_id,
                    "name": staff["staff_name"],
                    "gate": g
                })

                idx += 1

        if day_list:
            scheduled_days[day] = day_list

    # persist updated priorities
    for staff in staff_map.values():
        supabase.table("staffs").update({
            "priority_count": staff["priority_count"],
            "priority_updated_month": month_date,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("staff_id", staff["staff_id"]).execute()

    return jsonify({
        "month": month_input,
        "scheduled_days": scheduled_days,
        "shortage_days": list(set(shortage_days))
    }), 200


# ---------------- RESET PRIORITY ----------------
@app.route("/reset-priority", methods=["POST"])
def reset_priority():
    data = request.get_json(force=True)
    confirmation = data.get("confirmation")

    if confirmation != "CONFIRM":
        return jsonify({"error": "Confirmation failed"}), 400

    supabase.table("staffs").update({
        "priority_count": 0,
        "priority_updated_month": None,
        "updated_at": datetime.utcnow().isoformat()
    }).execute()

    return jsonify({"message": "All staff priorities reset"}), 200


# ---------------- DELETE MONTH ----------------
@app.route("/delete-month", methods=["POST"])
def delete_month_schedule():
    data = request.get_json(force=True)
    month = data.get("month")
    confirmation = data.get("confirmation")

    if confirmation != "CONFIRM":
        return jsonify({"error": "Type CONFIRM"}), 400

    month_date = month + "-01"

    supabase.table("monthly_schedule") \
        .delete() \
        .eq("month", month_date) \
        .execute()

    return jsonify({"message": f"{month} deleted"}), 200


# ---------------- VIEW MONTH ----------------
@app.route("/schedule/<month>", methods=["GET"])
def view_month_schedule(month):
    month_date = month + "-01"

    res = supabase.table("monthly_schedule") \
        .select("staff_id, weekday, gate") \
        .eq("month", month_date) \
        .execute()

    return jsonify(res.data), 200


# ---------------- VIEW STAFF ----------------
@app.route("/staffs", methods=["GET"])
def view_staffs():
    res = supabase.table("staffs") \
        .select("staff_id, staff_name, priority_count, priority_updated_month") \
        .order("staff_id") \
        .execute()

    return jsonify(res.data), 200


# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run(debug=True)
