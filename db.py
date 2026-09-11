import threading
from datetime import datetime, timezone, timedelta

WINDOW_MINUTES = 8640 #This is for 6 months of data, 6 months = 4320 hours = 259200 minutes.  This is for the database to keep data for 6 months.  The front end will only show the last 2 hours of data.
ONLINE_THRESHOLD_MIN = 5
KNOWN_DEVICES = ["TG452-01", "TG452-02", "TG452-03", "TG452-04", "TG452-05"]


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
                    "wbgt": float(r.get("wbgt", 0)),
                })
                added += 1
            self._rows = [x for x in self._rows
                          if self._parse_ts(x["ts"]) >= cutoff]
            self._rows.sort(key=lambda x: x["ts"])
        return added

    def query(self, device=None, since=None, start=None, end=None, minutes=WINDOW_MINUTES):
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        since_dt = self._parse_ts(since) if since else None
        start_dt = self._parse_ts(start) if start else None
        end_dt = self._parse_ts(end) if end else None
        if start_dt and end_dt and start_dt > end_dt:
            raise ValueError("start must be before end")
        with self._lock:
            rows = list(self._rows)
        out = []
        for r in rows:
            ts = self._parse_ts(r["ts"])
            if start_dt and ts < start_dt:
                continue
            if end_dt and ts > end_dt:
                continue
            if not start_dt and ts < cutoff:
                continue
            if since_dt and ts <= since_dt:
                continue
            if device and r["device"] != device:
                continue
            out.append(r)
        return out

    def delete_device(self, device):
        with self._lock:
            before = len(self._rows)
            self._rows = [r for r in self._rows if r["device"] != device]
            return before - len(self._rows)

    def devices(self):
        with self._lock:
            return sorted({r["device"] for r in self._rows})

    def count(self):
        with self._lock:
            return len(self._rows)

    def devices_status(self):
        """
        Return status for every KNOWN device, whether or not it has data.
        For each device:
          - online: True if last reading < ONLINE_THRESHOLD_MIN
          - last_seen: ISO timestamp of latest reading in window, or None
          - latest: the latest reading dict, or None
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=WINDOW_MINUTES)
        online_cutoff = now - timedelta(minutes=ONLINE_THRESHOLD_MIN)

        with self._lock:
            rows = list(self._rows)

        # device -> latest row
        latest_by_device = {}
        for r in rows:
            try:
                ts = self._parse_ts(r["ts"])
            except Exception:
                continue
            if ts < cutoff:
                continue
            d = r["device"]
            if d not in latest_by_device or ts > self._parse_ts(latest_by_device[d]["ts"]):
                latest_by_device[d] = r

        out = []
        for device in KNOWN_DEVICES:
            r = latest_by_device.get(device)
            if r is None:
                out.append({
                    "device": device,
                    "online": False,
                    "last_seen": None,
                    "latest": None,
                })
                continue
            ts = self._parse_ts(r["ts"])
            out.append({
                "device": device,
                "online": ts >= online_cutoff,
                "last_seen": r["ts"],
                "latest": r,
            })
        return out


store = Store()