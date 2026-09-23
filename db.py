import threading
from datetime import datetime, timezone, timedelta

WINDOW_MINUTES = 120
ONLINE_THRESHOLD_MIN = 5
# The full identifier is used for ingestion, access control, and exports.  The
# short name is only for presentation in the dashboard.
DEVICES = {
    "KNF-B452BF260717021": "KNF",
    "KWRP-B452BF260731002": "KWRP",
    "JWRP-B452BF260731009": "JWRP",
    "UPWRP-B452BF260731003": "UPWRP",
    "CWRP-B452BF260717023": "CWRP",
}
KNOWN_DEVICES = list(DEVICES)

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
            if r is None:
                out.append({
                    "device": device,
                    "label": DEVICES[device],
                    "online": False,
                    "last_seen": None,
                    "latest": None,
                })
                continue
            ts = self._parse_ts(r["timestamp"])
            out.append({
                "device": device,
                "label": DEVICES[device],
                "online": ts >= online_cutoff,
                "last_seen": r["timestamp"],
                "latest": r,
            })
        return out

# class Store:
#     def __init__(self):
#         self._lock = threading.Lock()
#         self._rows = []

#     @staticmethod
#     def _parse_ts(ts):
#         if isinstance(ts, (int, float)):
#             return datetime.fromtimestamp(ts, tz=timezone.utc)
#         s = str(ts).replace("Z", "+00:00")
#         dt = datetime.fromisoformat(s)
#         if dt.tzinfo is None:
#             dt = dt.replace(tzinfo=timezone.utc)
#         return dt.astimezone(timezone.utc)

#     def add_many(self, records):
#         cutoff = datetime.now(timezone.utc) - timedelta(minutes=WINDOW_MINUTES)
#         added = 0
#         with self._lock:
#             for r in records:
#                 try:
#                     ts = self._parse_ts(r["ts"])
#                 except Exception:
#                     continue
#                 if ts < cutoff:
#                     continue
#                 self._rows.append({
#                     "ts": str(r["ts"]).replace("Z", "+00:00"),
#                     "device": str(r["device"]),
#                     "battery_voltage": float(r.get("battery_voltage", 0)),
#                     "felt_temp": float(r.get("felt_temp", 0)),
#                     "surround_temp": float(r.get("surround_temp", 0)),
#                     "humidity": float(r.get("humidity", 0)),
#                     "wbgt": float(r.get("wbgt", 0)),
#                 })
#                 added += 1
#             self._rows = [x for x in self._rows
#                           if self._parse_ts(x["ts"]) >= cutoff]
#             self._rows.sort(key=lambda x: x["ts"])
#         return added

#     def query(self, device=None, since=None, minutes=WINDOW_MINUTES):
#         cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
#         since_dt = self._parse_ts(since) if since else None
#         with self._lock:
#             rows = list(self._rows)
#         out = []
#         for r in rows:
#             ts = self._parse_ts(r["ts"])
#             if ts < cutoff:
#                 continue
#             if since_dt and ts <= since_dt:
#                 continue
#             if device and r["device"] != device:
#                 continue
#             out.append(r)
#         return out

#     def query_window(self, from_dt, to_dt, devices=None):
#         devices_set = set(devices) if devices else None
#         with self._lock:
#             rows = list(self._rows)
#         out = []
#         for r in rows:
#             ts = self._parse_ts(r["ts"])
#             if ts < from_dt or ts > to_dt:
#                 continue
#             if devices_set and r["device"] not in devices_set:
#                 continue
#             out.append(r)
#         out.sort(key=lambda x: x["ts"])
#         return out

#     def delete_device(self, device):
#         with self._lock:
#             before = len(self._rows)
#             self._rows = [r for r in self._rows if r["device"] != device]
#             return before - len(self._rows)

#     def devices(self):
#         with self._lock:
#             return sorted({r["device"] for r in self._rows})

#     def count(self):
#         with self._lock:
#             return len(self._rows)

#     def devices_status(self):
#         now = datetime.now(timezone.utc)
#         cutoff = now - timedelta(minutes=WINDOW_MINUTES)
#         online_cutoff = now - timedelta(minutes=ONLINE_THRESHOLD_MIN)

#         with self._lock:
#             rows = list(self._rows)

#         latest_by_device = {}
#         for r in rows:
#             try:
#                 ts = self._parse_ts(r["ts"])
#             except Exception:
#                 continue
#             if ts < cutoff:
#                 continue
#             d = r["device"]
#             if d not in latest_by_device or ts > self._parse_ts(latest_by_device[d]["ts"]):
#                 latest_by_device[d] = r

#         out = []
#         for device in KNOWN_DEVICES:
#             r = latest_by_device.get(device)
#             if r is None:
#                 out.append({"device": device, "online": False, "last_seen": None, "latest": None})
#                 continue
#             ts = self._parse_ts(r["ts"])
#             out.append({
#                 "device": device,
#                 "online": ts >= online_cutoff,
#                 "last_seen": r["ts"],
#                 "latest": r,
#             })
#         return out


store = Store()
