"""
device_hub.py
Manages connected TG452s. No threads — one HTTP handler per device owns the WS.
"""
import json
import queue
import threading

_sessions = {}
_lock = threading.Lock()


class Session:
    def __init__(self, station_id, ws):
        self.station_id = station_id
        self.ws = ws
        self.out_queue = queue.Queue()
        self.browser_streams = []
        self.sync_exports = []
        self.browser_lock = threading.Lock()
        self.sync_lock = threading.Lock()

    def send(self, obj):
        if isinstance(obj, str):
            self.out_queue.put(obj)
        else:
            self.out_queue.put(json.dumps(obj))

    def dispatch(self, msg):
        t = msg.get("type")

        if t == "archive_chunk":
            with self.browser_lock:
                for bws in list(self.browser_streams):
                    try:
                        bws.send(json.dumps(msg))
                    except Exception:
                        pass
            with self.sync_lock:
                for exp in list(self.sync_exports):
                    try:
                        exp["queue"].put(("chunk", msg.get("data", "")))
                    except Exception:
                        pass

        elif t == "archive_end":
            with self.browser_lock:
                for bws in list(self.browser_streams):
                    try:
                        bws.send(json.dumps({"type": "archive_end", "size": msg.get("size", 0)}))
                    except Exception:
                        pass
                    try:
                        bws.close()
                    except Exception:
                        pass
                self.browser_streams.clear()
            with self.sync_lock:
                for exp in list(self.sync_exports):
                    try:
                        exp["queue"].put(("end", msg.get("size", 0)))
                    except Exception:
                        pass
                self.sync_exports.clear()

        elif t == "error":
            err = msg.get("message", "unknown error")
            with self.browser_lock:
                for bws in list(self.browser_streams):
                    try:
                        bws.send(json.dumps({"type": "error", "message": err}))
                    except Exception:
                        pass
                    try:
                        bws.close()
                    except Exception:
                        pass
                self.browser_streams.clear()
            with self.sync_lock:
                for exp in list(self.sync_exports):
                    try:
                        exp["queue"].put(("error", err))
                    except Exception:
                        pass
                self.sync_exports.clear()

    def add_browser_streamer(self, browser_ws):
        with self.browser_lock:
            self.browser_streams.append(browser_ws)

    def remove_browser_streamer(self, browser_ws):
        with self.browser_lock:
            if browser_ws in self.browser_streams:
                self.browser_streams.remove(browser_ws)

    def start_sync_export(self):
        q = queue.Queue()
        with self.sync_lock:
            self.sync_exports.append({"queue": q})
        self.send({"type": "give_archive"})
        return q


def register_session(station_id, sess):
    with _lock:
        old = _sessions.get(station_id)
        _sessions[station_id] = sess
        return old


def unregister_session(station_id, sess):
    with _lock:
        cur = _sessions.get(station_id)
        if cur is sess:
            del _sessions[station_id]


def get(station_id):
    with _lock:
        return _sessions.get(station_id)


def online_stations():
    with _lock:
        return list(_sessions.keys())