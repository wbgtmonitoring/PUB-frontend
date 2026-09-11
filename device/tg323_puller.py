"""Runs on a TG323. Pulls new records from Render every 60s."""
import os, time, logging
import requests

RENDER_URL = os.environ["RENDER_URL"].rstrip("/")
API_TOKEN  = os.environ.get("API_TOKEN", "").strip()
DEVICE_ID  = os.environ.get("DEVICE_ID", "TG323-01")
INTERVAL   = 60
LAST_TS_FILE = f"/tmp/{DEVICE_ID}_last_ts.txt"

def get_last_ts():
    try:
        with open(LAST_TS_FILE) as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None

def save_last_ts(ts):
    with open(LAST_TS_FILE, "w") as f:
        f.write(ts)

def persist(records):
    """Write to your local 1-hour store on the TG323 (SQLite/file/etc.)."""
    # e.g. sqlite3 insert here
    pass

def pull_once():
    params = {"minutes": 120}
    since = get_last_ts()
    if since:
        params["since"] = since
    headers = {}
    if API_TOKEN:
        headers["X-Device-Token"] = API_TOKEN
    try:
        r = requests.get(f"{RENDER_URL}/api/readings", params=params, headers=headers, timeout=20)
        r.raise_for_status()
        rows = r.json().get("readings", [])
        if not rows:
            logging.info("no new records")
            return
        persist(rows)
        save_last_ts(rows[-1]["ts"])
        logging.info("pulled %d (last ts %s)", len(rows), rows[-1]["ts"])
    except Exception as e:
        logging.warning("pull failed, will retry next tick: %s", e)

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    while True:
        t0 = time.time()
        pull_once()
        time.sleep(max(1, INTERVAL - (time.time() - t0)))

if __name__ == "__main__":
    main()