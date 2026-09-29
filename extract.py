import csv
import re
from datetime import datetime, timezone
from pathlib import Path

CSV_FIELDS = ["timestamp", "station_id", "device_id",
              "air_temp", "rel_humidity", "bg_temp", "wbgt", "batt_volt"]

_MONTHLY = re.compile(r"^(?P<station>[A-Z0-9]+)_(?P<month>\d{4}-\d{2})_backup\.csv$")


def _parse_ts(s):
    s = (s or "").strip().replace("Z", "+00:00")
    if not s:
        raise ValueError("empty timestamp")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def pick_files(archive_dir, station, from_dt, to_dt):
    wanted = []
    from_month = f"{from_dt.year:04d}-{from_dt.month:02d}"
    to_month   = f"{to_dt.year:04d}-{to_dt.month:02d}"
    for f in sorted(Path(archive_dir).glob("*_backup.csv")):
        m = _MONTHLY.match(f.name)
        if not m or m.group("station") != station:
            continue
        if from_month <= m.group("month") <= to_month:
            wanted.append(f)
    return wanted


def extract_range(archive_dir, station, from_dt, to_dt):
    rows = []
    for f in pick_files(archive_dir, station, from_dt, to_dt):
        try:
            with f.open("r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    try:
                        ts = _parse_ts(row.get("timestamp"))
                    except Exception:
                        continue
                    if ts < from_dt or ts > to_dt:
                        continue
                    row["_ts"] = ts
                    # Synthesize the "device" key that app.py's _build_csv expects
                    row["device"] = f"{row.get('station_id','')}-{row.get('device_id','')}"
                    rows.append(row)
        except Exception:
            continue
    rows.sort(key=lambda r: r["_ts"])
    for r in rows:
        r.pop("_ts", None)
    return rows