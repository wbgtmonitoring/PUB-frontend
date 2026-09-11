import os
import io
import csv
import zipfile
import base64
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests as http_requests

from db import store

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)

API_TOKEN          = os.environ.get("API_TOKEN", "").strip()
RESEND_API_KEY     = os.environ.get("RESEND_API_KEY", "").strip()
RESEND_FROM        = os.environ.get("RESEND_FROM", "PUB Dashboard <onboarding@resend.dev>").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def _authorized():
    if not API_TOKEN:
        return True
    return request.headers.get("X-Device-Token") == API_TOKEN


CSV_HEADERS = [
    "Timestamp (SGT)", "Timestamp (UTC)", "Device",
    "Battery (V)", "BG Temp (C)", "Air Temp (C)", "Humidity (%)", "WBGT (C)"
]

SGT = timezone(timedelta(hours=8))


def _fmt_sgt(iso):
    if not iso:
        return "--"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(SGT).strftime("%d/%m/%Y, %H:%M:%S SGT")
    except Exception:
        return iso


def _build_csv(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_HEADERS)
    for r in rows:
        w.writerow([
            _fmt_sgt(r["ts"]),
            r["ts"],
            r["device"],
            f"{float(r.get('battery_voltage', 0)):.2f}",
            f"{float(r.get('felt_temp', 0)):.2f}",
            f"{float(r.get('surround_temp', 0)):.2f}",
            f"{float(r.get('humidity', 0)):.2f}",
            f"{float(r.get('wbgt', 0)):.2f}",
        ])
    return buf.getvalue()


def _build_export_zip(rows, stamp):
    by_device = {}
    for r in rows:
        by_device.setdefault(r["device"], []).append(r)
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as z:
        for device, list_ in by_device.items():
            z.writestr(f"pub_{device}_{stamp}.csv", _build_csv(list_))
        z.writestr(f"pub_ALL_{stamp}.csv", _build_csv(rows))
    zip_buf.seek(0)
    return zip_buf.read()


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


@app.route("/api/export", methods=["POST"])
def export_readings():
    payload = request.get_json(silent=True) or {}
    method  = (payload.get("method") or "").lower()
    from_iso = payload.get("from")
    to_iso   = payload.get("to")
    devices  = payload.get("devices") or []

    if not from_iso or not to_iso or not devices:
        return jsonify({"error": "from, to, and devices are required"}), 400

    try:
        from_dt = datetime.fromisoformat(from_iso.replace("Z", "+00:00")).astimezone(timezone.utc)
        to_dt   = datetime.fromisoformat(to_iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return jsonify({"error": "invalid from/to timestamps"}), 400

    rows = store.query_window(from_dt, to_dt, devices)
    if not rows:
        return jsonify({"error": "no readings match these filters"}), 404

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H-%M-%S")
    unique_devices = sorted({r["device"] for r in rows})

    if len(unique_devices) > 1:
        attachment_bytes = _build_export_zip(rows, stamp)
        filename = f"pub_export_{stamp}.zip"
        content_type = "application/zip"
    else:
        attachment_bytes = _build_csv(rows).encode("utf-8")
        filename = f"pub_export_{stamp}.csv"
        content_type = "text/csv"

    # ---------- EMAIL ----------
    if method == "email":
        recipient = (payload.get("email") or "").strip()
        if not recipient:
            return jsonify({"error": "email is required"}), 400
        if not RESEND_API_KEY:
            return jsonify({"error": "server missing RESEND_API_KEY"}), 500

        subject = payload.get("subject") or f"PUB data export ({len(rows)} readings)"
        body_text = payload.get("body") or (
            f"Hello,\n\nAttached is the PUB device export.\n"
            f"Devices: {', '.join(unique_devices)}\n"
            f"Readings: {len(rows)}\n\nRegards"
        )
        body_html = "<pre style='font-family:inherit;white-space:pre-wrap'>" + \
                    body_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") + \
                    "</pre>"

        try:
            resp = http_requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": RESEND_FROM,
                    "to": [recipient],
                    "subject": subject,
                    "text": body_text,
                    "html": body_html,
                    "attachments": [{
                        "filename": filename,
                        "content": base64.b64encode(attachment_bytes).decode(),
                    }],
                },
                timeout=30,
            )
            if resp.status_code >= 400:
                return jsonify({
                    "error": "resend failed",
                    "status": resp.status_code,
                    "detail": resp.text[:400],
                }), 502
            return jsonify({
                "sent": True, "method": "email",
                "to": recipient, "readings": len(rows), "filename": filename,
            })
        except Exception as e:
            return jsonify({"error": f"email send failed: {e}"}), 502

    # ---------- TELEGRAM ----------
    if method == "telegram":
        chat_id = str(payload.get("telegram_chat_id") or "").strip()
        if not chat_id:
            return jsonify({"error": "telegram_chat_id is required"}), 400
        if not TELEGRAM_BOT_TOKEN:
            return jsonify({"error": "server missing TELEGRAM_BOT_TOKEN"}), 500

        message = payload.get("telegram_message") or (
            f"PUB export: {len(rows)} readings across {len(unique_devices)} device(s)."
        )
        try:
            r1 = http_requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": message},
                timeout=20,
            )
            if r1.status_code >= 400:
                return jsonify({
                    "error": "telegram sendMessage failed",
                    "status": r1.status_code,
                    "detail": r1.text[:400],
                }), 502

            r2 = http_requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument",
                data={"chat_id": chat_id, "caption": filename},
                files={"document": (filename, attachment_bytes, content_type)},
                timeout=60,
            )
            if r2.status_code >= 400:
                return jsonify({
                    "error": "telegram sendDocument failed",
                    "status": r2.status_code,
                    "detail": r2.text[:400],
                }), 502
            return jsonify({
                "sent": True, "method": "telegram",
                "chat_id": chat_id, "readings": len(rows), "filename": filename,
            })
        except Exception as e:
            return jsonify({"error": f"telegram send failed: {e}"}), 502

    return jsonify({"error": "method must be 'email' or 'telegram'"}), 400


@app.route("/")
def index():
    return send_from_directory("static", "pub_web.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))