#!/usr/bin/env python3
import os, sys, json, time, subprocess, http.cookiejar, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

BASE_URL     = "https://pub-frontend.onrender.com"
LOGIN_URL    = BASE_URL + "/api/auth/login"
DATA_URL     = BASE_URL + "/api/readings?minutes=10"
THRESH_URL   = BASE_URL + "/api/bg-thresholds/"

USERNAME     = "pub2"
PASSWORD     = "KWRP-2"

REFRESH      = 60
STALE_AFTER  = timedelta(minutes=5)
SGT          = timezone(timedelta(hours=8))

# Re-fetch thresholds every 60s so UI edits show up quickly
THRESH_REFRESH = 60

DEVICES = {
    "KNF-B452BF260717021":   "KNF",
    "KWRP-B452BF260731002":  "KWRP",
    "JWRP-B452BF260731009":  "JWRP",
    "UPWRP-B452BF260731003": "UPWRP",
    "CWRP-B452BF260717023":  "CWRP",
}

STATION_ID  = os.environ.get("STATION_ID", "KWRP-B452BF260731002")
DCT_SPEED   = "8"

MESSAGES = {
    "good":    "Normal activities. Stay hydrated.",
    "average": "Heat stress elevated. Reduce outdoor activity.",
    "bad":     "High risk. Minimise outdoor activity. Stay under shade.",
}

DEFAULT_THRESHOLDS = {
    "good_below": 31.0,
    "avg_from":   31.0,
    "avg_to":     33.0,
    "bad_above":  33.0,
}

ESC    = "\033"
CLEAR  = ESC + "[2J" + ESC + "[H"
BOLD   = ESC + "[1m"
DIM    = ESC + "[2m"
RESET  = ESC + "[0m"
CYAN   = ESC + "[36m"
GREEN  = ESC + "[32m"
YELLOW = ESC + "[33m"
RED    = ESC + "[31m"
WHITE  = ESC + "[97m"


def out(s=""):
    sys.stdout.write(s + "\n")
    sys.stdout.flush()


def parse_ts(iso):
    if not iso:
        return None
    try:
        s = iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def get_ts(reading):
    if not reading:
        return ""
    for k in ("ts", "timestamp", "time", "datetime"):
        v = reading.get(k)
        if v:
            return v
    return ""


def fmt_sgt(iso):
    dt = parse_ts(iso)
    if dt is None:
        return "--"
    return dt.astimezone(SGT).strftime("%d/%m/%Y, %H:%M:%S SGT")


def age_str(iso):
    dt = parse_ts(iso)
    if dt is None:
        return "never"
    diff = (datetime.now(timezone.utc) - dt).total_seconds()
    if diff < 0:
        return "just now"
    if diff < 60:
        return str(int(diff)) + "s ago"
    if diff < 3600:
        return str(int(diff // 60)) + "m ago"
    return str(int(diff // 3600)) + "h ago"


def short_name(device_id):
    if device_id in DEVICES:
        return DEVICES[device_id]
    return device_id.split("-")[0] if device_id else "?"


_cookiejar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookiejar))


def login():
    payload = json.dumps({"username": USERNAME, "password": PASSWORD}).encode()
    req = urllib.request.Request(
        LOGIN_URL,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "TG323-Station-Monitor/1.0",
        },
    )
    with _opener.open(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def clear_cookies():
    for c in list(_cookiejar):
        _cookiejar.clear(c.domain, c.path, c.name)


def fetch_readings():
    for attempt in (1, 2):
        try:
            req = urllib.request.Request(
                DATA_URL,
                headers={"User-Agent": "TG323-Station-Monitor/1.0"},
            )
            with _opener.open(req, timeout=20) as resp:
                body = json.loads(resp.read().decode())
            return body.get("readings", []), None
        except urllib.error.HTTPError as e:
            if e.code == 401 and attempt == 1:
                clear_cookies()
                try:
                    login()
                except Exception as le:
                    return None, "login failed: " + str(le)
                continue
            return None, "HTTPError: " + str(e)
        except Exception as e:
            return None, type(e).__name__ + ": " + str(e)
    return None, "unreachable"


def fetch_thresholds(device_id):
    """Fetch thresholds, cache-busted so we always get the latest."""
    url = THRESH_URL + device_id + "?t=" + str(int(time.time()))
    for attempt in (1, 2):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "TG323-Station-Monitor/1.0",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                },
            )
            with _opener.open(req, timeout=20) as resp:
                body = json.loads(resp.read().decode())
            t = body.get("thresholds") or {}
            needed = ("good_below", "avg_from", "avg_to", "bad_above")
            if all(k in t for k in needed):
                return t, None
            return dict(DEFAULT_THRESHOLDS), "incomplete thresholds"
        except urllib.error.HTTPError as e:
            if e.code == 401 and attempt == 1:
                clear_cookies()
                try:
                    login()
                except Exception as le:
                    return dict(DEFAULT_THRESHOLDS), "login failed: " + str(le)
                continue
            return dict(DEFAULT_THRESHOLDS), "HTTPError " + str(e.code)
        except Exception as e:
            return dict(DEFAULT_THRESHOLDS), type(e).__name__ + ": " + str(e)
    return dict(DEFAULT_THRESHOLDS), "unreachable"


def fnum(v, decimals=2):
    try:
        return ("{:." + str(decimals) + "f}").format(float(v))
    except Exception:
        return "--"


def classify(wbgt_value, thresholds):
    """Return 'good' | 'average' | 'bad' based on the WBGT value."""
    try:
        v = float(wbgt_value)
    except (TypeError, ValueError):
        return None
    if v < thresholds["good_below"]:
        return "good"
    if v <= thresholds["avg_to"]:
        return "average"
    return "bad"


def thresholds_equal(a, b):
    """Compare two threshold dicts for equality (float-safe)."""
    if not a or not b:
        return False
    for k in ("good_below", "avg_from", "avg_to", "bad_above"):
        try:
            if abs(float(a.get(k, 0)) - float(b.get(k, 0))) > 1e-6:
                return False
        except (TypeError, ValueError):
            return False
    return True


_last_display_text = None


def send_to_display(reading, thresholds):
    """Push the WBGT + message string to the DCT LED display.
    Skips the push if the text hasn't changed (prevents flicker)."""
    global _last_display_text
    if not reading:
        return
    wbgt_val = reading.get("wbgt")
    wbgt = fnum(wbgt_val, 2)
    zone = classify(wbgt_val, thresholds) or "good"
    message = MESSAGES.get(zone, MESSAGES["good"])

    text = "WBGT: " + wbgt + " | " + message

    if text == _last_display_text:
        return  # no change — don't re-push

    try:
        subprocess.run(
            ["dct-led", "--persist", text, DCT_SPEED],
            timeout=5,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _last_display_text = text
    except Exception:
        pass


def draw(reading, err, thresholds, thresh_err, thresh_changed):
    sys.stdout.write(CLEAR)
    name = short_name(STATION_ID)

    out(CYAN + BOLD + "=" * 60 + RESET)
    out(CYAN + BOLD + "  " + name + "  -  Station Monitor (TG323)" + RESET)
    out(CYAN + BOLD + "=" * 60 + RESET)
    out()

    if err:
        out("  Station:     " + WHITE + STATION_ID + RESET)
        out("  Status:      " + RED + "CONNECTION ERROR" + RESET)
        out("  Detail:      " + err)
        out()
        out(DIM + "  Retrying every " + str(REFRESH) + "s. Ctrl+C to exit." + RESET)
        return

    if reading is None:
        out("  Station:     " + WHITE + STATION_ID + RESET)
        out("  Status:      " + YELLOW + "NO DATA (last 10 min)" + RESET)
        out()
        out(DIM + "  Retrying every " + str(REFRESH) + "s. Ctrl+C to exit." + RESET)
        return

    ts = get_ts(reading)
    ts_dt = parse_ts(ts)
    stale = (datetime.now(timezone.utc) - ts_dt) > STALE_AFTER if ts_dt else True

    if stale:
        status = YELLOW + "STALE" + RESET
    else:
        status = GREEN + "ONLINE" + RESET

    bg       = reading.get("bg_temp")
    hum      = reading.get("rel_humidity")
    air      = reading.get("air_temp")
    wbgt_val = reading.get("wbgt")
    batt     = reading.get("batt_volt")

    zone = classify(wbgt_val, thresholds)
    zone_color = {"good": GREEN, "average": YELLOW, "bad": RED, None: DIM}[zone]
    zone_text = zone.upper() if zone else "UNKNOWN"
    zone_msg = MESSAGES.get(zone, "-") if zone else "-"

    out("  Station:     " + WHITE + STATION_ID + RESET)
    out("  Status:      " + status)
    out("  Last update: " + WHITE + fmt_sgt(ts) + RESET)
    out("  Age:         " + age_str(ts))
    out()

    out(BOLD + CYAN + "+-- Latest Values --------------------------------------+" + RESET)
    out("  Blackglobe Temp      " + fnum(bg, 2).rjust(8) + " C")
    out("  Rel Humidity         " + fnum(hum, 2).rjust(8) + " %")
    out("  Air Temp             " + fnum(air, 2).rjust(8) + " C")
    out("  WBGT                 " + fnum(wbgt_val, 2).rjust(8) + " C  <= used for zone")
    out("  Battery              " + fnum(batt, 2).rjust(8) + " V")
    out(BOLD + CYAN + "+-------------------------------------------------------+" + RESET)
    out()

    out(BOLD + CYAN + "+-- LED Display Output ---------------------------------+" + RESET)
    if zone is None:
        out("  Zone:         " + DIM + "UNKNOWN (no WBGT value)" + RESET)
    else:
        out("  Zone:         " + zone_color + BOLD + zone_text + RESET
            + DIM + "   (WBGT=" + fnum(wbgt_val, 2) + ")" + RESET)
    out("  Message:      " + zone_msg)
    out("  Display text: " + WHITE + "WBGT: " + fnum(wbgt_val, 2) + " | " + zone_msg + RESET)
    out(BOLD + CYAN + "+-------------------------------------------------------+" + RESET)
    out()

    if thresh_err:
        out(YELLOW + "  Thresholds fallback: " + thresh_err + RESET)
    else:
        line = ("  Thresholds:  good<" + fnum(thresholds["good_below"], 2)
                + " | avg " + fnum(thresholds["avg_from"], 2)
                + "-" + fnum(thresholds["avg_to"], 2)
                + " | bad>" + fnum(thresholds["bad_above"], 2)
                + "  (from server)")
        out(DIM + line + RESET)

    if thresh_changed:
        out(GREEN + BOLD + "  [SYNC] Thresholds updated from dashboard" + RESET)

    out()
    out(DIM + "  Refreshing every " + str(REFRESH) + "s. Ctrl+C to exit." + RESET)


def main():
    try:
        for attempt in range(1, 61):
            try:
                login()
                break
            except Exception:
                time.sleep(5)
    except Exception:
        pass

    thresholds = dict(DEFAULT_THRESHOLDS)
    thresh_err = None
    last_thresh_fetch = 0.0
    thresh_changed = False

    try:
        while True:
            t0 = time.time()

            # Refresh thresholds every THRESH_REFRESH seconds
            if t0 - last_thresh_fetch > THRESH_REFRESH:
                t, err = fetch_thresholds(STATION_ID)
                if not thresholds_equal(t, thresholds):
                    thresh_changed = True
                    # Force a display refresh even if the WBGT hasn't changed,
                    # because the message (based on thresholds) has changed.
                    global _last_display_text
                    _last_display_text = None
                else:
                    thresh_changed = False
                thresholds = t
                thresh_err = err
                last_thresh_fetch = t0

            rows, err = fetch_readings()
            if err is None and rows:
                rows.sort(key=lambda r: get_ts(r))
                reading = rows[-1]
            else:
                reading = None

            if reading:
                send_to_display(reading, thresholds)

            draw(reading, err, thresholds, thresh_err, thresh_changed)
            thresh_changed = False

            elapsed = time.time() - t0
            time.sleep(max(1, REFRESH - elapsed))

    except KeyboardInterrupt:
        out("\n" + GREEN + "Station monitor stopped." + RESET)


if __name__ == "__main__":
    main()