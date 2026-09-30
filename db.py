import threading
from datetime import datetime, timezone, timedelta

WINDOW_MINUTES = 60 * 24 * 180     # 180 days ≈ 6 months
ONLINE_THRESHOLD_MIN = 5

DEVICES = {
    "KNF-B452BF260717021": "KNF",
    "KWRP-B452BF260731002": "KWRP",
    "JWRP-B452BF260731009": "JWRP",
    "UPWRP-B452BF260731003": "UPWRP",
    "CWRP-B452BF260717023": "CWRP",
}
KNOWN_DEVICES = list(DEVICES)

DEFAULT_BG_THRESHOLDS = {
    "good_below": 31.0,
    "avg_from":   31.0,
    "avg_to":     33.0,
    "bad_above":  33.0,
}


class Store:
    def __init__(self):
        self._lock = threading.Lock()
        self._rows = []
        self._thresholds = {}   # device_id -> dict of 4 floats

    # ------------------------------------------------------------------
    # Readings
    # ------------------------------------------------------------------
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
                    ts = self._parse_ts(r["timestamp"])
                except Exception:
                    continue
                if ts < cutoff:
                    continue

                self._rows.append({
                    "timestamp": str(r["timestamp"]).replace("Z", "+00:00"),
                    "station_id": str(r.get("station_id", "")),
                    "device_id": str(r.get("device_id", "")),
                    "device": f"{r.get('station_id', '')}-{r.get('device_id', '')}",
                    "air_temp": float(r.get("air_temp") or 0),
                    "rel_humidity": float(r.get("rel_humidity") or 0),
                    "bg_temp": float(r.get("bg_temp") or 0),
                    "wbgt": float(r.get("wbgt") or 0),
                    "batt_volt": float(r.get("batt_volt") or 0),
                })
                added += 1
            self._rows = [x for x in self._rows
                          if self._parse_ts(x["timestamp"]) >= cutoff]
            self._rows.sort(key=lambda x: x["timestamp"])
        return added

    def query(self, device=None, since=None, minutes=WINDOW_MINUTES):
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        since_dt = self._parse_ts(since) if since else None
        with self._lock:
            rows = list(self._rows)
        out = []
        for r in rows:
            ts = self._parse_ts(r["timestamp"])
            if ts < cutoff:
                continue
            if since_dt and ts <= since_dt:
                continue
            if device and r["device"] != device:
                continue
            out.append(r)
        return out

    def query_window(self, from_dt, to_dt, devices=None):
        devices_set = set(devices) if devices else None
        with self._lock:
            rows = list(self._rows)
        out = []
        for r in rows:
            ts = self._parse_ts(r["timestamp"])
            if ts < from_dt or ts > to_dt:
                continue
            if devices_set and r["device"] not in devices_set:
                continue
            out.append(r)
        out.sort(key=lambda x: x["timestamp"])
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
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=WINDOW_MINUTES)
        online_cutoff = now - timedelta(minutes=ONLINE_THRESHOLD_MIN)

        with self._lock:
            rows = list(self._rows)

        latest_by_device = {}
        for r in rows:
            try:
                ts = self._parse_ts(r["timestamp"])
            except Exception:
                continue
            if ts < cutoff:
                continue
            d = r["device"]
            if d not in latest_by_device or ts > self._parse_ts(latest_by_device[d]["timestamp"]):
                latest_by_device[d] = r

        out = []
        for device in KNOWN_DEVICES:
            r = latest_by_device.get(device)
            bg_thresholds = self.get_thresholds(device)
            if r is None:
                out.append({
                    "device": device,
                    "label": DEVICES[device],
                    "online": False,
                    "last_seen": None,
                    "latest": None,
                    "bg_thresholds": bg_thresholds,
                })
                continue
            ts = self._parse_ts(r["timestamp"])
            out.append({
                "device": device,
                "label": DEVICES[device],
                "online": ts >= online_cutoff,
                "last_seen": r["timestamp"],
                "latest": r,
                "bg_thresholds": bg_thresholds,
            })
        return out

    # ------------------------------------------------------------------
    # BG thresholds
    # ------------------------------------------------------------------
    def get_thresholds(self, device):
        with self._lock:
            override = self._thresholds.get(device)
        return dict(override) if override else dict(DEFAULT_BG_THRESHOLDS)

    def get_all_thresholds(self):
        return {device: self.get_thresholds(device) for device in KNOWN_DEVICES}

    def set_thresholds(self, device, values):
        good  = float(values["good_below"])
        afrom = float(values["avg_from"])
        ato   = float(values["avg_to"])
        bad   = float(values["bad_above"])

        if not (good < afrom):
            raise ValueError("good_below must be < avg_from")
        if not (afrom < ato):
            raise ValueError("avg_from must be < avg_to")
        if not (ato <= bad):
            raise ValueError("avg_to must be <= bad_above")

        with self._lock:
            self._thresholds[device] = {
                "good_below": good,
                "avg_from":   afrom,
                "avg_to":     ato,
                "bad_above":  bad,
            }
        return self.get_thresholds(device)

    def reset_thresholds(self, device):
        with self._lock:
            self._thresholds.pop(device, None)
        return self.get_thresholds(device)

    def classify_bg(self, device, bg_temp):
        t = self.get_thresholds(device)
        try:
            v = float(bg_temp)
        except (TypeError, ValueError):
            return "unknown"
        if v < t["good_below"]:
            return "good"
        if v <= t["avg_to"]:
            return "average"
        return "bad"


store = Store()