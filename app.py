import os
import io
import csv
import zipfile
import json
import base64
import hmac
import time
import queue
import logging
import secrets
import requests
from functools import wraps
from datetime import datetime, timezone, timedelta
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, session, g
from flask_cors import CORS
from flask_sock import Sock
from device_hub import (
    register_session, unregister_session,
    get as get_device, online_stations, Session,
)
import requests as http_requests

from db import store, DEFAULT_BG_THRESHOLDS
from auth import ACCOUNTS

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)
sock = Sock(app)

app.config.update(
    SECRET_KEY=os.environ.get("DASHBOARD_SECRET_KEY") or secrets.token_urlsafe(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

API_TOKEN          = os.environ.get("API_TOKEN", "").strip()
RESEND_API_KEY     = os.environ.get("RESEND_API_KEY", "").strip()
RESEND_FROM        = os.environ.get("RESEND_FROM", "PUB Dashboard <onboarding@resend.dev>").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
WETEC_PUB_API      = os.environ.get("WETEC_PUB_API").strip()

log = logging.getLogger("export")
log.setLevel(logging.INFO)


def _authorized():
    if not API_TOKEN:
        return True
    return request.headers.get("X-Device-Token") == API_TOKEN


def _current_account():
    username = session.get("username")
    account = ACCOUNTS.get(username)
    if not account:
        return None
    return {"username": username, **account}


def _dashboard_login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        account = _current_account()
        if not account:
            return jsonify({"error": "login required"}), 401
        g.account = account
        return view(*args, **kwargs)
    return wrapped


def _allowed_devices():
    return None if g.account["device"] is None else {g.account["device"]}


def _require_allowed_device(device):
    allowed = _allowed_devices()
    return allowed is None or device in allowed


CSV_HEADERS = [
    "Timestamp (SGT)", "Device",
    "Battery (V)", "Blackglobe Temp (C)", "Air Temp (C)", "Rel Humidity (%)", "WBGT (C)"
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


def _safe_float(v, default=0.0):
    if v is None:
        return default
    s = str(v).strip()
    if s == "" or s.lower() == "none":
        return default
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


def _build_csv(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_HEADERS)
    for r in rows:
        w.writerow([
            _fmt_sgt(r.get("timestamp")),
            r.get("device", ""),
            f"{_safe_float(r.get('batt_volt')):.2f}",
            f"{_safe_float(r.get('bg_temp')):.2f}",
            f"{_safe_float(r.get('air_temp')):.2f}",
            f"{_safe_float(r.get('rel_humidity')):.2f}",
            f"{_safe_float(r.get('wbgt')):.2f}",
        ])
    return buf.getvalue()


def _build_export_zip(rows_by_device, stamp):
    zip_buf = io.BytesIO()
    all_rows = []
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as z:
        for device, list_ in rows_by_device.items():
            if not list_:
                continue
            list_.sort(key=lambda r: r["timestamp"])
            z.writestr(f"pub_{device}_{stamp}.csv", _build_csv(list_))
            all_rows.extend(list_)
        all_rows.sort(key=lambda r: r["timestamp"])
        z.writestr(f"pub_ALL_{stamp}.csv", _build_csv(all_rows))
    zip_buf.seek(0)
    return zip_buf.read()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@app.route("/api/auth/login", methods=["POST"])
def login():
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username") or "").strip().lower()
    password = str(payload.get("password") or "")
    account = ACCOUNTS.get(username)
    if not account or not hmac.compare_digest(password, account["password"]):
        return jsonify({"error": "invalid username or password"}), 401

    session.clear()
    session["username"] = username
    return jsonify({
        "username": username,
        "role": "admin" if account["device"] is None else "station",
        "device": account["device"],
    })


@app.route("/api/auth/me", methods=["GET"])
def current_user():
    account = _current_account()
    if not account:
        return jsonify({"error": "login required"}), 401
    return jsonify({
        "username": account["username"],
        "role": "admin" if account["device"] is None else "station",
        "device": account["device"],
    })


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"logged_out": True})


# ---------------------------------------------------------------------------
# WT PUB BACKEND API FAILOVER
# ---------------------------------------------------------------------------
@app.route("/api/<station_id>/thresholds", methods=["GET"])
def get_station_thresholds(station_id):
    # if not _authorized():
    #     return jsonify({"error": "unauthorized"}), 401

    if not WETEC_PUB_API:
        return jsonify({"error": "WT server configuration missing"}), 401
    
    threshold_api_uri = f"{WETEC_PUB_API}/config/{station_id}/thresholds"

    try:
        # GET req to thresholds table and query for station ID
        response = requests.get(threshold_api_uri, timeout=10)
        
        # Raise an exception for HTTP error codes (4xx, 5xx)
        response.raise_for_status()
        
        # Forward the JSON response back to the frontend
        return jsonify(response.json()), 200
        
    except requests.exceptions.RequestException as e:
        # Handle connection errors, timeouts, or HTTP errors gracefully
        return jsonify({
            "error": "Failed to fetch station thresholds", 
            "details": str(e)
        }), 502

@app.route("/api/<station_id>/thresholds", methods=["PUT"])
def update_station_thresholds(station_id):
    if not _authorized():
        return jsonify({"error": "unauthorized"}), 401

    threshold_api_uri = f"{WETEC_PUB_API}/config/{station_id}/thresholds"

    # Extract the JSON payload sent by frontend
    payload = request.get_json()

    if not payload:
        return jsonify({"error": "Invalid or missing JSON payload"}), 400

    try:
        # Forward the PUT request and the JSON payload to the backend server
        response = requests.put(threshold_api_uri, json=payload, timeout=10)
        
        # Raise an exception for HTTP error codes (4xx, 5xx)
        response.raise_for_status()
        
        # Forward the successful JSON response back to the frontend
        return jsonify(response.json()), response.status_code
        
    except requests.exceptions.RequestException as e:
        # Handle connection errors, timeouts, or HTTP errors gracefully
        return jsonify({
            "error": "Failed to update station thresholds", 
            "details": str(e)
        }), 502

# ---------------------------------------------------------------------------
# Readings
# ---------------------------------------------------------------------------
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
@_dashboard_login_required
def get_readings():
    device = request.args.get("device")
    if device and not _require_allowed_device(device):
        return jsonify({"error": "device access denied"}), 403
    since = request.args.get("since")
    try:
        minutes = int(request.args.get("minutes", 259200))
    except ValueError:
        minutes = 60 * 24 * 180
    minutes = max(1, min(minutes, 259200))
    allowed = _allowed_devices()
    if allowed is not None:
        device = next(iter(allowed))
    rows = store.query(device=device, since=since, minutes=minutes)
    return jsonify({"count": len(rows), "readings": rows})


@app.route("/api/readings/<device>", methods=["DELETE"])
@_dashboard_login_required
def delete_device_readings(device):
    if not _require_allowed_device(device):
        return jsonify({"error": "device access denied"}), 403
    deleted = store.delete_device(device)
    return jsonify({"deleted": deleted, "device": device})


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------
@app.route("/api/devices", methods=["GET"])
@_dashboard_login_required
def get_devices():
    allowed = _allowed_devices()
    devices = store.devices()
    if allowed is not None:
        devices = [device for device in devices if device in allowed]
    return jsonify({"devices": devices})


@app.route("/api/devices/status", methods=["GET"])
@_dashboard_login_required
def get_devices_status():
    allowed = _allowed_devices()
    devices = store.devices_status()
    if allowed is not None:
        devices = [device for device in devices if device["device"] in allowed]
    return jsonify({"devices": devices})


@app.route("/api/devices/connected", methods=["GET"])
@_dashboard_login_required
def get_connected_devices():
    allowed = _allowed_devices()
    online = online_stations()
    if allowed is not None:
        online = [s for s in online if s in allowed]
    return jsonify({"online": online, "count": len(online)})


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "ok": True,
        "buffered": store.count(),
        "ws_online": len(online_stations()),
    })


# ---------------------------------------------------------------------------
# BG thresholds
# ---------------------------------------------------------------------------
@app.route("/api/bg-thresholds", methods=["GET"])
@_dashboard_login_required
def get_all_bg_thresholds():
    allowed = _allowed_devices()
    all_t = store.get_all_thresholds()
    if allowed is not None:
        all_t = {d: t for d, t in all_t.items() if d in allowed}
    return jsonify({"thresholds": all_t, "defaults": DEFAULT_BG_THRESHOLDS})


@app.route("/api/bg-thresholds/<device>", methods=["GET"])
@_dashboard_login_required
def get_device_bg_thresholds(device):
    if not _require_allowed_device(device):
        return jsonify({"error": "device access denied"}), 403
    return jsonify({
        "device": device,
        "thresholds": store.get_thresholds(device),
        "defaults": DEFAULT_BG_THRESHOLDS,
    })


@app.route("/api/bg-thresholds/<device>", methods=["PUT"])
@_dashboard_login_required
def put_device_bg_thresholds(device):
    if not _require_allowed_device(device):
        return jsonify({"error": "device access denied"}), 403

    payload = request.get_json(silent=True) or {}

    if payload.get("reset") is True:
        return jsonify({
            "device": device,
            "thresholds": store.reset_thresholds(device),
            "reset": True,
        })

    required = ["good_below", "avg_from", "avg_to", "bad_above"]
    missing = [k for k in required if k not in payload]
    if missing:
        return jsonify({"error": f"missing fields: {', '.join(missing)}"}), 400

    try:
        updated = store.set_thresholds(device, {
            "good_below": payload["good_below"],
            "avg_from":   payload["avg_from"],
            "avg_to":     payload["avg_to"],
            "bad_above":  payload["bad_above"],
        })
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({"device": device, "thresholds": updated})


# ---------------------------------------------------------------------------
# Export via WebSocket
# ---------------------------------------------------------------------------
def _collect_from_device(sess, from_dt, to_dt, timeout=120):
    log.warning("[EXPORT] collect station=%s from=%s to=%s",
                sess.station_id, from_dt.isoformat(), to_dt.isoformat())

    q = sess.start_sync_export()

    buf = io.BytesIO()
    deadline = time.time() + timeout
    chunks = 0

    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            log.warning("[EXPORT] TIMEOUT chunks=%d bytes=%d", chunks, buf.tell())
            raise TimeoutError("device did not respond in time")
        try:
            kind, value = q.get(timeout=remaining)
        except queue.Empty:
            log.warning("[EXPORT] queue empty chunks=%d bytes=%d", chunks, buf.tell())
            raise TimeoutError("device stream timed out")

        if kind == "chunk":
            try:
                buf.write(base64.b64decode(value))
                chunks += 1
            except Exception as e:
                log.warning("[EXPORT] chunk decode err: %s", e)
                continue
        elif kind == "end":
            log.warning("[EXPORT] end chunks=%d bytes=%d", chunks, buf.tell())
            break
        elif kind == "error":
            raise RuntimeError(value)

    buf.seek(0)
    text = buf.read().decode("utf-8", errors="replace")
    log.warning("[EXPORT] preview:\n%r", text[:400])

    reader = csv.DictReader(io.StringIO(text))
    rows = []
    skip_parse = 0
    skip_range = 0
    first_ts = last_ts = None

    for r in reader:
        ts_raw = r.get("timestamp") or r.get("Timestamp") or ""
        if not ts_raw:
            skip_parse += 1
            continue
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            skip_parse += 1
            continue
        if first_ts is None:
            first_ts = ts
        last_ts = ts
        if ts < from_dt or ts > to_dt:
            skip_range += 1
            continue
        rows.append({
            "timestamp":     ts.isoformat(),
            "device":        f"{r.get('station_id','')}-{r.get('device_id','')}",
            "batt_volt":     _safe_float(r.get("batt_volt")),
            "bg_temp":       _safe_float(r.get("bg_temp")),
            "air_temp":      _safe_float(r.get("air_temp")),
            "rel_humidity":  _safe_float(r.get("rel_humidity")),
            "wbgt":          _safe_float(r.get("wbgt")),
        })

    log.warning("[EXPORT] parsed=%d skip_parse=%d skip_range=%d first=%s last=%s",
                len(rows), skip_parse, skip_range, first_ts, last_ts)
    return rows


@app.route("/api/export", methods=["POST"])
@_dashboard_login_required
def export_readings():
    payload = request.get_json(silent=True) or {}
    method    = (payload.get("method") or "download").lower()
    from_iso  = payload.get("from")
    to_iso    = payload.get("to")
    devices   = payload.get("devices") or []

    log.warning("[EXPORT] request method=%s from=%s to=%s devices=%s",
                method, from_iso, to_iso, devices)

    if not from_iso or not to_iso or not devices:
        return jsonify({"error": "from, to, and devices are required"}), 400

    if any(not isinstance(d, str) or not _require_allowed_device(d) for d in devices):
        return jsonify({"error": "device access denied"}), 403

    try:
        from_dt = datetime.fromisoformat(from_iso.replace("Z", "+00:00")).astimezone(timezone.utc)
        to_dt   = datetime.fromisoformat(to_iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return jsonify({"error": "invalid from/to timestamps"}), 400
    if from_dt > to_dt:
        return jsonify({"error": "from must be before to"}), 400

    rows_by_device = {}
    warnings = []

    for device in devices:
        sess = get_device(device)
        if sess is None:
            log.warning("[EXPORT] offline: %s", device)
            warnings.append({"device": device, "error": "device offline"})
            rows_by_device[device] = []
            continue
        try:
            rows_by_device[device] = _collect_from_device(sess, from_dt, to_dt, timeout=120)
        except Exception as e:
            log.warning("[EXPORT] collect failed %s: %s", device, e)
            warnings.append({"device": device, "error": f"{type(e).__name__}: {e}"})
            rows_by_device[device] = []

    total = sum(len(v) for v in rows_by_device.values())
    log.warning("[EXPORT] total=%d warnings=%s", total, warnings)

    if total == 0:
        return jsonify({
            "error": "no readings match these filters",
            "details": warnings or None,
        }), 404

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H-%M-%S")
    unique_devices = [d for d in devices if rows_by_device.get(d)]

    if len(unique_devices) > 1:
        attachment_bytes = _build_export_zip(rows_by_device, stamp)
        filename = f"pub_export_{stamp}.zip"
        content_type = "application/zip"
    else:
        only = unique_devices[0] if unique_devices else devices[0]
        attachment_bytes = _build_csv(rows_by_device[only]).encode("utf-8")
        filename = f"pub_export_{stamp}.csv"
        content_type = "text/csv"

    if method == "download":
        return jsonify({
            "filename": filename,
            "content_type": content_type,
            "readings": total,
            "warnings": warnings or None,
            "content_b64": base64.b64encode(attachment_bytes).decode(),
        })

    if method == "email":
        recipient = (payload.get("email") or "").strip()
        if not recipient:
            return jsonify({"error": "email is required"}), 400
        if not RESEND_API_KEY:
            return jsonify({"error": "server missing RESEND_API_KEY"}), 500

        subject = payload.get("subject") or f"PUB data export ({total} readings)"
        body_text = payload.get("body") or (
            f"Hello,\n\nAttached is the PUB device export.\n"
            f"Devices: {', '.join(unique_devices)}\n"
            f"Readings: {total}\n\nRegards"
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
                timeout=60,
            )
            if resp.status_code >= 400:
                return jsonify({
                    "error": "resend failed",
                    "status": resp.status_code,
                    "detail": resp.text[:400],
                }), 502
            return jsonify({
                "sent": True, "method": "email",
                "to": recipient, "readings": total, "filename": filename,
                "warnings": warnings or None,
            })
        except Exception as e:
            return jsonify({"error": f"email send failed: {e}"}), 502

    return jsonify({"error": f"unknown method: {method}"}), 400


# ---------------------------------------------------------------------------
# WebSocket — device
# ---------------------------------------------------------------------------
@sock.route("/ws/device")
def ws_device(ws):
    import simple_websocket

    try:
        raw = ws.receive(timeout=15)
        hello = json.loads(raw)
    except Exception:
        try:
            ws.send(json.dumps({"type": "error", "message": "bad hello"}))
        except Exception:
            pass
        return

    if hello.get("type") != "hello":
        ws.send(json.dumps({"type": "error", "message": "expected hello"}))
        return

    station_id = str(hello.get("station_id") or "").strip()
    token      = str(hello.get("token") or "").strip()

    if API_TOKEN and token != API_TOKEN:
        ws.send(json.dumps({"type": "error", "message": "unauthorized"}))
        return

    if not station_id:
        ws.send(json.dumps({"type": "error", "message": "no station_id"}))
        return

    sess = Session(station_id, ws)
    old = register_session(station_id, sess)
    if old:
        try:
            old.ws.close()
        except Exception:
            pass

    ws.send(json.dumps({"type": "welcome", "station_id": station_id}))
    log.warning("[WS-DEV] connected: %s", station_id)

    last_ping = time.time()

    try:
        while True:
            # Drain outgoing queue
            try:
                while True:
                    m = sess.out_queue.get_nowait()
                    if m is None:
                        return
                    try:
                        ws.send(m)
                    except Exception:
                        return
            except queue.Empty:
                pass

            # Server-side ping every 25s
            if time.time() - last_ping > 25:
                try:
                    ws.send(json.dumps({"type": "ping"}))
                except Exception:
                    return
                last_ping = time.time()

            # Read (short timeout so loop returns often)
            try:
                raw = ws.receive(timeout=0.5)
            except simple_websocket.ConnectionClosed:
                return
            except Exception:
                continue

            if raw is None:
                continue

            try:
                msg = json.loads(raw)
            except Exception:
                continue

            sess.dispatch(msg)
    finally:
        log.warning("[WS-DEV] disconnected: %s", station_id)
        unregister_session(station_id, sess)


# ---------------------------------------------------------------------------
# WebSocket — archive (browser)
# ---------------------------------------------------------------------------
@sock.route("/ws/archive")
def ws_archive(ws):
    account = _current_account()
    if not account:
        ws.send(json.dumps({"type": "error", "message": "login required"}))
        return

    station = request.args.get("station") or ""
    if not station:
        ws.send(json.dumps({"type": "error", "message": "station required"}))
        return

    if account["device"] is not None and account["device"] != station:
        ws.send(json.dumps({"type": "error", "message": "access denied"}))
        return

    sess = get_device(station)
    if sess is None:
        ws.send(json.dumps({"type": "error", "message": "device offline"}))
        return

    sess.add_browser_streamer(ws)
    sess.send({"type": "give_archive"})

    try:
        while True:
            ws.receive(timeout=300)
    except Exception:
        pass
    finally:
        sess.remove_browser_streamer(ws)


@app.route("/")
def index():
    return send_from_directory("static", "pub_web.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))