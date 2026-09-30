import os
import io
import csv
import zipfile
import base64
import hmac
import secrets
from functools import wraps
from datetime import datetime, timezone, timedelta
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, session, g
from flask_cors import CORS
import requests as http_requests
from extract import extract_range
from archive_store import ArchiveStore
import traceback as _tb

from db import store, DEFAULT_BG_THRESHOLDS
from auth import ACCOUNTS

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)

app.config.update(
    SECRET_KEY=os.environ.get("DASHBOARD_SECRET_KEY") or secrets.token_urlsafe(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

API_TOKEN          = os.environ.get("API_TOKEN", "").strip()
RESEND_API_KEY     = os.environ.get("RESEND_API_KEY", "").strip()
RESEND_FROM        = os.environ.get("RESEND_FROM", "PUB Dashboard <onboarding@resend.dev>").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


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
ARCHIVE_DIR = Path(os.environ.get("ARCHIVE_DIR", "archive"))
archive_store = ArchiveStore(ARCHIVE_DIR)


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
            list_.sort(key=lambda r: r["timestamp"])
            z.writestr(f"pub_{device}_{stamp}.csv", _build_csv(list_))
            all_rows.extend(list_)
        all_rows.sort(key=lambda r: r["timestamp"])
        z.writestr(f"pub_ALL_{stamp}.csv", _build_csv(all_rows))
    zip_buf.seek(0)
    return zip_buf.read()


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


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "buffered": store.count()})


# ---------------------------------------------------------------------------
# BG Thresholds
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
# Archive
# ---------------------------------------------------------------------------
@app.route("/api/archive/push", methods=["POST"])
def archive_push():
    if not _authorized():
        return jsonify({"error": "unauthorized"}), 401

    filename = request.headers.get("X-Filename", "")
    try:
        start_byte = int(request.headers.get("X-Append-From", "0"))
    except ValueError:
        return jsonify({"error": "invalid X-Append-From"}), 400

    data = request.get_data()

    try:
        ok, info = archive_store.append_chunk(filename, start_byte, data)
    except ValueError:
        return jsonify({"error": "invalid filename"}), 400

    if not ok:
        return jsonify({
            "error": info.get("error", "append failed"),
            "expected": info.get("expected"),
            "actual": info.get("actual"),
        }), 409

    return jsonify({
        "filename": filename,
        "received": len(data),
        "total": info["new_total"],
    }), 201


@app.route("/api/archive/list", methods=["GET"])
@_dashboard_login_required
def archive_list():
    return jsonify({"files": archive_store.list_files()})


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
@app.route("/api/export", methods=["POST"])
@_dashboard_login_required
def export_readings():
    payload = request.get_json(silent=True) or {}
    method   = (payload.get("method") or "download").lower()
    from_iso = payload.get("from")
    to_iso   = payload.get("to")
    devices  = payload.get("devices") or []

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
    for full_device in devices:
        station = full_device.split("-", 1)[0]
        try:
            rows_by_device[full_device] = extract_range(ARCHIVE_DIR, station, from_dt, to_dt)
        except Exception as e:
            warnings.append({
                "device": full_device,
                "error": f"{type(e).__name__}: {e}",
                "traceback": _tb.format_exc().splitlines()[-6:],
            })
            rows_by_device[full_device] = []

    total = sum(len(v) for v in rows_by_device.values())
    if total == 0:
        return jsonify({
            "error": "no readings match these filters",
            "details": warnings or None,
        }), 404

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H-%M-%S")
    unique_devices = sorted(rows_by_device.keys())

    if len(unique_devices) > 1:
        attachment_bytes = _build_export_zip(rows_by_device, stamp)
        filename = f"pub_export_{stamp}.zip"
        content_type = "application/zip"
    else:
        only = unique_devices[0]
        attachment_bytes = _build_csv(rows_by_device[only]).encode("utf-8")
        filename = f"pub_export_{stamp}.csv"
        content_type = "text/csv"

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

    return jsonify({
        "filename": filename,
        "content_type": content_type,
        "readings": total,
        "warnings": warnings or None,
        "content_b64": base64.b64encode(attachment_bytes).decode(),
    })


# ---------------------------------------------------------------------------
# DEBUG — filesystem inspector (admin only, free-tier friendly)
# ---------------------------------------------------------------------------
@app.route("/api/debug/files", methods=["GET"])
@_dashboard_login_required
def debug_files():
    """List files in the container. Admin only. Replaces the need for a shell."""
    if g.account.get("device") is not None:
        return jsonify({"error": "admin only"}), 403

    base = Path(os.getcwd())
    out = {
        "cwd": str(base),
        "archive_dir": str(ARCHIVE_DIR),
        "store_path": os.environ.get("STORE_PATH", "readings_store.json"),
        "files": [],
        "archive": [],
    }

    def _stat(f):
        try:
            st = f.stat()
            return {
                "name": f.name,
                "type": "dir" if f.is_dir() else "file",
                "size": st.st_size if f.is_file() else None,
                "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            }
        except Exception as e:
            return {"name": f.name, "error": str(e)}

    try:
        for f in sorted(base.iterdir()):
            out["files"].append(_stat(f))
    except Exception as e:
        out["files_error"] = str(e)

    try:
        ad = Path(ARCHIVE_DIR)
        if ad.exists() and ad.is_dir():
            for f in sorted(ad.iterdir()):
                out["archive"].append(_stat(f))
    except Exception as e:
        out["archive_error"] = str(e)

    # Store file contents summary
    try:
        sp = Path(out["store_path"])
        if sp.exists():
            data = json.loads(sp.read_text())
            out["store_summary"] = {
                "exists": True,
                "size_bytes": sp.stat().st_size,
                "rows": len(data.get("rows", [])),
                "thresholds": len(data.get("thresholds", {})),
                "saved_at": data.get("saved_at"),
            }
        else:
            out["store_summary"] = {"exists": False}
    except Exception as e:
        out["store_summary"] = {"exists": True, "error": str(e)}

    return jsonify(out)


@app.route("/")
def index():
    return send_from_directory("static", "pub_web.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))