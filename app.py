import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from db import store

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)

API_TOKEN = os.environ.get("API_TOKEN", "").strip()

def _authorized():
    if not API_TOKEN:
        return True
    return request.headers.get("X-Device-Token") == API_TOKEN

@app.route("/api/readings", methods=["POST"])
def post_readings():
    if not _authorized():
        return jsonify({"error": "unauthorized"}), 401
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": "invalid json"}), 400
    records = payload if isinstance(payload, list) else [payload]
    added = store.add_many(records)
    return jsonify({"accepted": added, "buffered": store.count()}), 201

@app.route("/api/readings", methods=["GET"])
def get_readings():
    device = request.args.get("device")
    since = request.args.get("since")
    try:
        minutes = int(request.args.get("minutes", 120))
    except ValueError:
        minutes = 120
    minutes = max(1, min(minutes, 120))
    rows = store.query(device=device, since=since, minutes=minutes)
    return jsonify({"count": len(rows), "readings": rows})

@app.route("/api/readings/<device>", methods=["DELETE"])
def delete_device_readings(device):
    deleted = store.delete_device(device)
    return jsonify({"deleted": deleted, "device": device})

@app.route("/api/devices", methods=["GET"])
def get_devices():
    return jsonify({"devices": store.devices()})

@app.route("/api/devices/status", methods=["GET"])
def get_devices_status():
    return jsonify({"devices": store.devices_status()})

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "buffered": store.count()})

@app.route("/")
def index():
    return send_from_directory("static", "pub_web.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))