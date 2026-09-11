import threading
from datetime import datetime, timezone, timedelta

WINDOW_MINUTES = 120

class Store:
    def __init__(self):
        self._lock = threading.Lock()
        self._rows = []

    @staticmethod
    def _parse_ts(ts):
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        s = str(ts).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def add_many(self, records):
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=WINDOW_MINUTES)
        added = 0
        with self._lock:
            for r in records:
                try:
                    ts = self._parse_ts(r["ts"])
                except Exception:
                    continue
                if ts < cutoff:
                    continue
                self._rows.append({
                    "ts": ts.isoformat().replace("+00:00", "Z"),
                    "device": str(r["device"]),
                    "battery_voltage": float(r.get("battery_voltage", 0)),
                    "felt_temp": float(r.get("felt_temp", 0)),
                    "surround_temp": float(r.get("surround_temp", 0)),
                    "humidity": float(r.get("humidity", 0)),
                    "wbgt": float(r.get("wbgt", 0)),   # <-- NEW
                })
                added += 1
            self._rows = [x for x in self._rows
                          if self._parse_ts(x["ts"]) >= cutoff]
            self._rows.sort(key=lambda x: x["ts"])
        return added

    def query(self, device=None, since=None, minutes=WINDOW_MINUTES):
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        since_dt = self._parse_ts(since) if since else None
        with self._lock:
            rows = list(self._rows)
        out = []
        for r in rows:
            ts = self._parse_ts(r["ts"])
            if ts < cutoff:
                continue
            if since_dt and ts <= since_dt:
                continue
            if device and r["device"] != device:
                continue
            out.append(r)
        return out

    def devices(self):
        with self._lock:
            return sorted({r["device"] for r in self._rows})

    def count(self):
        with self._lock:
            return len(self._rows)

store = Store()