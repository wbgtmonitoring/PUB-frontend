"""
Runs on the server TG452. Every 60s it reads the latest reading for
each of the 5 stations and POSTs them to Render.

Fill in read_station() with your real local source (SQLite / file / serial).
"""
import os, time, logging
import requests

RENDER_URL = os.environ["RENDER_URL"].rstrip("/") + "/api/readings"
API_TOKEN  = os.environ.get("API_TOKEN", "").strip()
INTERVAL   = 60

DEVICES = ["TG452-01", "TG452-02", "TG452-03", "TG452-04", "TG452-05"]

def read_station(device_id):
    """Return the latest reading for a station or None.
    Replace with actual implementation, e.g. query a local SQLite:
        SELECT ts, battery_voltage, felt_temp, surround_temp, humidity
        FROM readings WHERE device=? ORDER BY ts DESC LIMIT 1
    """
    raise NotImplementedError

def push_once():
    records = []
    for dev in DEVICES:
        r = read_station(dev)
        if not r:
            continue
        records.append({
            "ts": r["ts"],                       # ISO8601 UTC, e.g. 2026-09-11T14:03:00Z
            "device": dev,
            "battery_voltage": r["battery_voltage"],
            "felt_temp": r["felt_temp"],
            "surround_temp": r["surround_temp"],
            "humidity": r["humidity"],
        })
    if not records:
        return
    headers = {"Content-Type": "application/json"}
    if API_TOKEN:
        headers["X-Device-Token"] = API_TOKEN
    try:
        resp = requests.post(RENDER_URL, json=records, headers=headers, timeout=20)
        resp.raise_for_status()
        logging.info("pushed %d: %s", len(records), resp.json())
    except Exception as e:
        logging.warning("push failed, will retry next tick: %s", e)

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    while True:
        t0 = time.time()
        push_once()
        time.sleep(max(1, INTERVAL - (time.time() - t0)))

if __name__ == "__main__":
    main()