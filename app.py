import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from flask import Flask, jsonify, request

from decorators.request_log import request_log
from singletons.requests import Requests

app = Flask(__name__)

# Weekly calories burned while keeping the same body weight, adults age 19+.
# min is the oldest age group, max is ages 19-30, daily figure times 7.
# not active, little activity, active, very active: normal-weight U.S. adults,
# National Academies of Sciences, Engineering, and Medicine, Dietary Reference
# Intakes for Energy (2023), Appendix M, Tables M-3 and M-4.
# moderate: Dietary Guidelines for Americans, 2020-2025, Table A2-2.
LIFESTYLE_ACTIVITY = {
    "not active": {
        "male": {"min_calories_per_week": 13461, "max_calories_per_week": 18151},
        "female": {"min_calories_per_week": 10955, "max_calories_per_week": 14105},
    },
    "little activity": {
        "male": {"min_calories_per_week": 14791, "max_calories_per_week": 19572},
        "female": {"min_calories_per_week": 12019, "max_calories_per_week": 15218},
    },
    "moderate": {
        "male": {"min_calories_per_week": 15400, "max_calories_per_week": 19600},
        "female": {"min_calories_per_week": 12600, "max_calories_per_week": 15400},
    },
    "active": {
        "male": {"min_calories_per_week": 16079, "max_calories_per_week": 20804},
        "female": {"min_calories_per_week": 12978, "max_calories_per_week": 16170},
    },
    "very active": {
        "male": {"min_calories_per_week": 17745, "max_calories_per_week": 22883},
        "female": {"min_calories_per_week": 14455, "max_calories_per_week": 17752},
    },
}

ACTIVITY_FOR_API = {
    "not active": "sedentary",
    "little activity": "lightly_active",
    "moderate": "moderately_active",
    "active": "very_active",
    "very active": "extra_active",
}


@app.route("/log", methods=["POST"])
@request_log
def log_activity():
    return _log_activity()


def _log_activity():
    print("got a log request")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "body must be a json object"}), 400

    activity_type = body.get("type")
    minutes = body.get("minutes")
    if activity_type is None or minutes is None:
        return jsonify({"error": "type and minutes are required"}), 400

    try:
        minutes = float(minutes)
    except (TypeError, ValueError):
        return jsonify({"error": "minutes must be a number"}), 400

    if minutes <= 0:
        return jsonify({"error": "minutes must be greater than 0"}), 400

    if minutes == int(minutes):
        minutes = int(minutes)

    activities_file = open("data/activities.json", "r")
    activities = json.loads(activities_file.read())
    activities_file.close()

    found = None
    for row in activities:
        if row["name"] == activity_type:
            found = row
            break

    if found is None:
        return jsonify({"error": "unknown activity"}), 400

    calories = int(round(found["calories_per_60_min"] * minutes / 60))

    try:
        logs_file = open("data/logs.json", "r")
        logs = json.loads(logs_file.read())
        logs_file.close()
    except Exception as err:
        print("could not read logs", err)
        logs = []

    entry = {
        "type": activity_type,
        "minutes": minutes,
        "logged_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    logs.append(entry)

    out = open("data/logs.json", "w")
    out.write(json.dumps(logs, indent=2))
    out.close()

    print("saved", entry, "burned", calories)

    week_start = datetime.now() - timedelta(days=7)
    week_total = 0
    for item in logs:
        when = datetime.strptime(item["logged_at"], "%Y-%m-%dT%H:%M:%S")
        if when < week_start or when > datetime.now():
            continue
        activities_file = open("data/activities.json", "r")
        catalog = json.loads(activities_file.read())
        activities_file.close()
        per_hour = None
        for row in catalog:
            if row["name"] == item["type"]:
                per_hour = row["calories_per_60_min"]
                break
        if per_hour is None:
            continue
        week_total = week_total + int(round(per_hour * float(item["minutes"]) / 60))

    try:
        notices_file = open("data/notices.json", "r")
        notices = json.loads(notices_file.read())
        notices_file.close()
    except Exception as err:
        print("could not read notices", err)
        notices = []

    notices.append(
        {
            "event": "activity_logged",
            "type": entry["type"],
            "minutes": entry["minutes"],
            "calories": calories,
            "at": entry["logged_at"],
        }
    )
    if week_total >= 500:
        notices.append(
            {
                "event": "weekly_goal_reached",
                "calories": week_total,
                "goal": 500,
                "at": entry["logged_at"],
            }
        )
        print("weekly goal reached", week_total)

    notices_out = open("data/notices.json", "w")
    notices_out.write(json.dumps(notices, indent=2))
    notices_out.close()

    return jsonify(
        {
            "type": entry["type"],
            "minutes": entry["minutes"],
            "calories": calories,
            "logged_at": entry["logged_at"],
            "weekly_calories": week_total,
            "weekly_goal": 500,
            "goal_reached": week_total >= 500,
        }
    ), 201


@app.route("/log/undo", methods=["POST"])
@request_log
def undo_log():
    print("undo last log")
    try:
        logs_file = open("data/logs.json", "r")
        logs = json.loads(logs_file.read())
        logs_file.close()
    except Exception as err:
        print("could not read logs", err)
        logs = []

    if len(logs) == 0:
        return jsonify({"error": "nothing to undo"}), 400

    removed = logs.pop()
    out = open("data/logs.json", "w")
    out.write(json.dumps(logs, indent=2))
    out.close()
    print("undid", removed)
    return jsonify(removed), 200


@app.route("/notices", methods=["GET"])
@request_log
def list_notices():
    print("got a notices request")
    try:
        notices_file = open("data/notices.json", "r")
        notices = json.loads(notices_file.read())
        notices_file.close()
    except Exception as err:
        print("could not read notices", err)
        notices = []
    return jsonify(notices)


@app.route("/stats", methods=["GET"])
@request_log
def stats():
    stats = Requests.get_instance()
    print("got a stats request")
    return jsonify(
        {
            "count": stats.count,
            "last_path": stats.last_path,
            "last_seconds": stats.last_seconds,
        }
    )


@app.route("/activities", methods=["GET"])
@request_log
def list_activities():
    print("got an activities list request")
    activities_file = open("data/activities.json", "r")
    activities = json.loads(activities_file.read())
    activities_file.close()
    return jsonify(activities)


@app.route("/activities", methods=["POST"])
@request_log
def add_activity():
    return _add_activity()


def _add_activity():
    print("got an add activity request")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "body must be a json object"}), 400

    name = body.get("name")
    calories_per_60_min = body.get("calories_per_60_min")
    if name is None or calories_per_60_min is None:
        return jsonify({"error": "name and calories_per_60_min are required"}), 400

    if not isinstance(name, str) or name.strip() == "":
        return jsonify({"error": "name must be a non-empty string"}), 400

    name = name.strip()

    try:
        calories_per_60_min = float(calories_per_60_min)
    except (TypeError, ValueError):
        return jsonify({"error": "calories_per_60_min must be a number"}), 400

    if calories_per_60_min <= 0:
        return jsonify({"error": "calories_per_60_min must be greater than 0"}), 400

    if calories_per_60_min == int(calories_per_60_min):
        calories_per_60_min = int(calories_per_60_min)

    activities_file = open("data/activities.json", "r")
    activities = json.loads(activities_file.read())
    activities_file.close()

    for row in activities:
        if row["name"] == name:
            return jsonify({"error": "activity already exists"}), 400

    entry = {"name": name, "calories_per_60_min": calories_per_60_min}
    activities.append(entry)

    out = open("data/activities.json", "w")
    out.write(json.dumps(activities, indent=2))
    out.close()

    print("saved activity", entry)
    return jsonify(entry), 201


@app.route("/calories", methods=["GET"])
@request_log
def calories():
    return _calories()


def _calories():
    print("got a calories request", request.args)
    period = request.args.get("period")
    now = datetime.now()

    if period == "day":
        start = now - timedelta(days=1)
    elif period == "week":
        start = now - timedelta(days=7)
    elif period == "month":
        start = now - timedelta(days=30)
    else:
        return jsonify({"error": "period must be day, week or month"}), 400

    try:
        logs_file = open("data/logs.json", "r")
        logs = json.loads(logs_file.read())
        logs_file.close()
    except Exception as err:
        print("could not read logs", err)
        logs = []

    total = 0
    matched = []
    for item in logs:
        when = datetime.strptime(item["logged_at"], "%Y-%m-%dT%H:%M:%S")
        if when < start or when > now:
            continue

        activities_file = open("data/activities.json", "r")
        activities = json.loads(activities_file.read())
        activities_file.close()

        per_hour = None
        for row in activities:
            if row["name"] == item["type"]:
                per_hour = row["calories_per_60_min"]
                break

        if per_hour is None:
            print("skipping unknown activity", item["type"])
            continue

        burned = int(round(per_hour * float(item["minutes"]) / 60))
        total = total + burned
        matched.append(
            {
                "type": item["type"],
                "minutes": item["minutes"],
                "logged_at": item["logged_at"],
                "calories": burned,
            }
        )

    return jsonify(
        {
            "period": period,
            "from": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "to": now.strftime("%Y-%m-%dT%H:%M:%S"),
            "total_calories": total,
            "count": len(matched),
            "logs": matched,
        }
    )


@app.route("/user", methods=["POST"])
@request_log
def save_user():
    return _save_user()


def _save_user():
    print("got a save user request", request.args)
    age = request.args.get("age")
    gender = request.args.get("gender")
    weight_kg = request.args.get("weight_kg")
    height_cm = request.args.get("height_cm")
    goal = request.args.get("goal")

    if (
        age is None
        or gender is None
        or weight_kg is None
        or height_cm is None
        or goal is None
    ):
        return jsonify(
            {"error": "age, gender, weight_kg, height_cm and goal are required"}
        ), 400

    try:
        age = float(age)
        weight_kg = float(weight_kg)
        height_cm = float(height_cm)
    except (TypeError, ValueError):
        return jsonify({"error": "age, weight_kg and height_cm must be numbers"}), 400

    if age <= 0 or weight_kg <= 0 or height_cm <= 0:
        return jsonify(
            {"error": "age, weight_kg and height_cm must be greater than 0"}
        ), 400

    if age == int(age):
        age = int(age)
    if weight_kg == int(weight_kg):
        weight_kg = int(weight_kg)
    if height_cm == int(height_cm):
        height_cm = int(height_cm)

    gender = gender.strip().lower()
    if gender not in ("male", "female"):
        return jsonify({"error": "gender must be male or female"}), 400

    goal = goal.strip().lower()
    if goal not in ("lose", "maintain", "gain"):
        return jsonify({"error": "goal must be lose, maintain or gain"}), 400

    saved = {
        "age": age,
        "gender": gender,
        "weight_kg": weight_kg,
        "height_cm": height_cm,
        "goal": goal,
    }

    out = open("data/user.json", "w")
    out.write(json.dumps(saved, indent=2))
    out.close()

    print("saved user", saved)
    return jsonify(saved), 200


@app.route("/targets", methods=["GET"])
@request_log
def daily_targets():
    return _daily_targets()


def _daily_targets():
    print("got a targets request", request.args)
    period = request.args.get("period")
    now = datetime.now()

    if period == "day":
        start = now - timedelta(days=1)
    elif period == "week":
        start = now - timedelta(days=7)
    elif period == "month":
        start = now - timedelta(days=30)
    else:
        return jsonify({"error": "period must be day, week or month"}), 400

    try:
        user_file = open("data/user.json", "r")
        user = json.loads(user_file.read())
        user_file.close()
    except Exception as err:
        print("could not read user", err)
        return jsonify({"error": "user is not saved"}), 400

    if (
        "age" not in user
        or "gender" not in user
        or "weight_kg" not in user
        or "height_cm" not in user
        or "goal" not in user
    ):
        return jsonify({"error": "saved user is missing details"}), 400

    gender = user["gender"]
    if gender not in ("male", "female"):
        return jsonify({"error": "saved user gender is not supported"}), 400

    try:
        logs_file = open("data/logs.json", "r")
        logs = json.loads(logs_file.read())
        logs_file.close()
    except Exception as err:
        print("could not read logs", err)
        logs = []

    total = 0
    for item in logs:
        when = datetime.strptime(item["logged_at"], "%Y-%m-%dT%H:%M:%S")
        if when < start or when > now:
            continue

        activities_file = open("data/activities.json", "r")
        activities = json.loads(activities_file.read())
        activities_file.close()

        per_hour = None
        for row in activities:
            if row["name"] == item["type"]:
                per_hour = row["calories_per_60_min"]
                break

        if per_hour is None:
            print("skipping unknown activity", item["type"])
            continue

        burned = int(round(per_hour * float(item["minutes"]) / 60))
        total = total + burned

    if period == "day":
        weekly_calories = total * 7
    elif period == "week":
        weekly_calories = total
    else:
        weekly_calories = int(round(total * 7 / 30))

    level = "not active"
    for name in ("not active", "little activity", "moderate", "active", "very active"):
        band = LIFESTYLE_ACTIVITY[name][gender]
        if weekly_calories >= band["min_calories_per_week"]:
            level = name

    api_activity = ACTIVITY_FOR_API[level]
    query = urllib.parse.urlencode(
        {
            "age": user["age"],
            "gender": gender,
            "weight_kg": user["weight_kg"],
            "height_cm": user["height_cm"],
            "activity": api_activity,
            "goal": user["goal"],
        }
    )
    url = "https://calorieapiadmin.com/api/v1/public/calc/macros?" + query
    print("calling", url)

    try:
        outgoing = urllib.request.Request(
            url, headers={"User-Agent": "calorie-lab/1.0"}
        )
        remote = urllib.request.urlopen(outgoing, timeout=10)
        payload = json.loads(remote.read().decode())
        remote.close()
    except Exception as err:
        print("macros api failed", err)
        return jsonify({"error": "could not load daily targets"}), 502

    return jsonify(
        {
            "period": period,
            "calories_burned": total,
            "weekly_calories": weekly_calories,
            "activity_level": level,
            "activity": api_activity,
            "daily_targets": payload.get("daily_targets"),
            "bmr": payload.get("bmr"),
            "tdee": payload.get("tdee"),
        }
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
